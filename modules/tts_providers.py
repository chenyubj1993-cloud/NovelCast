# -*- coding: utf-8 -*-
"""TTS 提供方适配层。

支持两种后端：
1. IndexTTS-2（本地、GPU、零样本音色克隆，可带情绪文本）
2. edge-tts（微软免费在线音色，作为备用/参考音生成器）

对外统一接口：provider.synthesize(text, voice, output_path, emotion=None)
其中 voice 对 IndexTTS2 是参考音频路径，对 edge-tts 是音色名（如 zh-CN-YunxiNeural）。
"""
import asyncio
import os
import sys
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_paths():
    for p in (
        os.path.join(_PROJECT_ROOT, ".vendor"),
        os.path.join(_PROJECT_ROOT, "third_party", "index-tts"),
    ):
        if p not in sys.path:
            sys.path.insert(0, p)


# 角色 -> edge-tts 音色：既用于直接合成，也用于生成 IndexTTS-2 的参考音
EDGE_VOICE_MAP = {
    "旁白": "zh-CN-YunjianNeural",
    "叶秋": "zh-CN-YunxiNeural",
    "苏沐橙": "zh-CN-XiaoxiaoNeural",
    "陈果": "zh-CN-XiaoyiNeural",
    "经理": "zh-CN-YunyangNeural",
    "孙翔": "zh-CN-YunyeNeural",
    "唐柔": "zh-CN-XiaochenNeural",
    "包子": "zh-CN-YunxiaNeural",
    # cast 里存的是「音色名」，这里给出音色名到 Azure voice 的映射，
    # 这样 edge 直连和参考音生成都能按音色名解析。
    "冰糖": "zh-CN-XiaoxiaoNeural",
    "茉莉": "zh-CN-XiaoyiNeural",
    "Mia": "zh-CN-XiaochenNeural",
    "Chloe": "zh-CN-XiaohanNeural",
    "苏打": "zh-CN-XiaomengNeural",
    "白桦": "zh-CN-YunyangNeural",
    "Milo": "zh-CN-YunyeNeural",
    "Dean": "zh-CN-YunjianNeural",
    "晓晓": "zh-CN-XiaoxiaoNeural",
    "晓伊": "zh-CN-XiaoyiNeural",
    "晓辰": "zh-CN-XiaochenNeural",
    "云希": "zh-CN-YunxiNeural",
    "云扬": "zh-CN-YunyangNeural",
    "云健": "zh-CN-YunjianNeural",
    "云夜": "zh-CN-YunyeNeural",
    "云夏": "zh-CN-YunxiaNeural",
    "晓梦": "zh-CN-XiaomengNeural",
    "晓萱": "zh-CN-XiaoxuanNeural",
    "小北": "zh-CN-liaoning-XiaobeiNeural",
    "小妮": "zh-CN-shaanxi-XiaoniNeural",
}
DEFAULT_EDGE_VOICE = "zh-CN-YunxiNeural"


# 情绪 → 中文提示。Qwen 情绪编码器是中文语料训练的，传 "angry" 这种英文
# 单词信号很弱，换成中文描述后情绪强度明显更稳定。
EMOTION_PROMPTS = {
    "happy": "语气轻快，带一点笑意",
    "sad": "情绪低落，语速稍慢",
    "angry": "有些不悦，语气稍沉",
    "fear": "声音发紧，气息略不稳",
    "surprise": "略显意外，语调微扬",
    "disgust": "语气冷淡，略带不屑",
}

# 情绪 → 语速倍率（乘在基础 duration_factor 上，越小越快）
# 幅度刻意收窄：情绪是调味，不是表演，太快太慢都会显得夸张
EMOTION_SPEED = {
    "happy": 0.97,
    "sad": 1.06,
    "angry": 0.95,
    "fear": 0.98,
    "surprise": 0.96,
    "disgust": 0.98,
}

# 8 维情绪向量，顺序固定：happy, angry, sad, afraid, disgusted, melancholic, surprised, calm
EMOTION_VECTORS = {
    "happy": [1, 0, 0, 0, 0, 0, 0, 0],
    "angry": [0, 1, 0, 0, 0, 0, 0, 0],
    "sad": [0, 0, 1, 0, 0, 0, 0, 0],
    "fear": [0, 0, 0, 1, 0, 0, 0, 0],
    "disgust": [0, 0, 0, 0, 1, 0, 0, 0],
    "surprise": [0, 0, 0, 0, 0, 0, 1, 0],
}


class EdgeTTSProvider:
    name = "edge"

    def __init__(self, voice_map=None, rate="+0%"):
        _ensure_paths()
        self.voice_map = dict(EDGE_VOICE_MAP)
        if voice_map:
            self.voice_map.update(voice_map)
        self.rate = rate

    def resolve_voice(self, voice):
        if not voice:
            return DEFAULT_EDGE_VOICE
        if voice.startswith("zh-") or voice.startswith("en-"):
            return voice
        return self.voice_map.get(voice, DEFAULT_EDGE_VOICE)

    def synthesize(self, text, voice, output_path, emotion=None):
        import time

        import edge_tts

        voice_name = self.resolve_voice(voice)

        async def _run(name):
            communicate = edge_tts.Communicate(text, name, rate=self.rate)
            await communicate.save(output_path)

        def _run_sync(name):
            # 调用方可能已经在事件循环里（generate.py 是 async），此时不能再 asyncio.run
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(_run(name))
                return
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(asyncio.run, _run(name)).result()

        last_err = None
        for attempt in range(3):
            try:
                _run_sync(voice_name)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    return output_path
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(1.2 * (attempt + 1))
        # 换默认音色再试一次，避免个别音色被服务端拒绝
        if voice_name != DEFAULT_EDGE_VOICE:
            try:
                _run_sync(DEFAULT_EDGE_VOICE)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    return output_path
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise RuntimeError(f"edge-tts 合成失败（{voice_name}）: {last_err}")


class IndexTTS2Provider:
    name = "indextts2"
    _instance = None
    _lock = threading.Lock()

    def __init__(self, model_dir=None, use_fp16=True, device=None,
                 version="2", duration_factor=1.0, lang="zh", use_qwen_emo=None,
                 emotion_mode="text", emo_alpha=0.55):
        _ensure_paths()
        self.version = str(version)
        default_dir = "IndexTTS-2.5" if self.version.startswith("2.5") else "IndexTTS-2"
        self.model_dir = model_dir or os.path.join(_PROJECT_ROOT, "models", default_dir)
        self.cfg_path = os.path.join(self.model_dir, "config.yaml")
        self.use_fp16 = use_fp16
        self.device = device
        self.duration_factor = float(duration_factor)
        self.lang = lang
        self.use_qwen_emo = use_qwen_emo
        self.emotion_mode = emotion_mode  # text | vector | off
        self.emo_alpha = float(emo_alpha)
        self._emo_ok = False
        self._tts = None

    def _load(self):
        if self._tts is not None:
            return self._tts
        with IndexTTS2Provider._lock:
            if self._tts is None:
                is_v25 = self.version.startswith("2.5")
                if is_v25:
                    from indextts.infer_v2_5 import IndexTTS2
                    import indextts.infer_v2_5 as _iv
                else:
                    from indextts.infer_v2 import IndexTTS2
                    import indextts.infer_v2 as _iv
                import soundfile as _sf

                def _save_wav(path, wav, sampling_rate, **kwargs):
                    arr = wav.detach().cpu().float().numpy()
                    if arr.ndim == 2 and arr.shape[0] == 1:
                        arr = arr[0]
                    elif arr.ndim == 2:
                        arr = arr.T
                    # IndexTTS 输出是 int16 量纲（峰值可达 ±30000），不是 ±1；
                    # 直接按 PCM_16 写会被 libsndfile 削顶 → 严重失真。先归一化。
                    peak = float(abs(arr).max()) if arr.size else 0.0
                    if peak > 1.5:
                        arr = arr / 32768.0
                    _sf.write(path, arr, sampling_rate, format="WAV", subtype="PCM_16")

                # torchaudio>=2.9 保存要 TorchCodec，这里直接用 soundfile 落盘
                _iv.save_pcm_wav = _save_wav

                if is_v25:
                    # 2.5 的 __init__ 会无条件构造日文 G2P，依赖 MeCab/unidic。
                    # 本项目只读中文，缺依赖时用空实现顶替，避免为日文多装 50MB 词典。
                    try:
                        import MeCab  # noqa: F401
                    except Exception:
                        class _JaPassthrough:
                            def __init__(self, *args, **kwargs):
                                pass

                            def __call__(self, text, *args, **kwargs):
                                return text

                        _iv.JapaneseG2PProcessor = _JaPassthrough
                        print("ℹ️ 未检测到 MeCab，日文 G2P 使用空实现（仅影响日文）")
                    init_kwargs = dict(
                        cfg_path=self.cfg_path,
                        model_dir=self.model_dir,
                        use_bf16=bool(self.use_fp16),
                        device=self.device,
                    )
                    if self.use_qwen_emo is not False:
                        init_kwargs["use_qwen_emo"] = True
                    try:
                        self._tts = IndexTTS2(**init_kwargs)
                        self._emo_ok = bool(init_kwargs.get("use_qwen_emo"))
                    except Exception as exc:  # 显存不够等情况：退回不带文本情绪
                        print(f"⚠️ IndexTTS-2.5 带情绪模型加载失败（{exc}），回退为纯参考音情绪")
                        init_kwargs.pop("use_qwen_emo", None)
                        self._tts = IndexTTS2(**init_kwargs)
                        self._emo_ok = False
                else:
                    self._tts = IndexTTS2(
                        cfg_path=self.cfg_path,
                        model_dir=self.model_dir,
                        use_fp16=self.use_fp16,
                        device=self.device,
                    )
                    self._emo_ok = True
        return self._tts

    def synthesize(self, text, voice, output_path, emotion=None):
        tts = self._load()
        kwargs = dict(
            spk_audio_prompt=voice,
            text=text,
            output_path=output_path,
            verbose=False,
        )
        if self.version.startswith("2.5"):
            kwargs["lang"] = self.lang
            kwargs["duration_factor"] = self.duration_factor
        emo = (emotion or "").strip()
        if emo and emo not in ("neutral", "平静") and self._emo_ok and self.emotion_mode != "off":
            if self.version.startswith("2.5"):
                # 情绪直接影响语速：生气/惊讶略快，悲伤放慢
                factor = self.duration_factor * EMOTION_SPEED.get(emo, 1.0)
                kwargs["duration_factor"] = max(0.5, min(2.0, factor))
                kwargs["emo_alpha"] = max(0.0, min(1.0, self.emo_alpha))
            if self.emotion_mode == "vector" and emo in EMOTION_VECTORS:
                kwargs["emo_vector"] = EMOTION_VECTORS[emo]
            else:
                kwargs["use_emo_text"] = True
                kwargs["emo_text"] = EMOTION_PROMPTS.get(emo, emo)
        tts.infer(**kwargs)
        return output_path


def build_provider(config, name=None):
    """按配置构建 TTS 提供方。config 为 config_manager.Config 实例或 dict。"""
    data = getattr(config, "config", config) or {}
    tts_cfg = data.get("tts", {}) if isinstance(data, dict) else {}
    name = name or tts_cfg.get("provider") or "indextts2"
    if name == "edge":
        return EdgeTTSProvider(voice_map=tts_cfg.get("edge_voice_map"))
    if name in ("indextts2", "indextts2.5"):
        version = tts_cfg.get("model_version") or ("2.5" if name.endswith("2.5") else "2")
        return IndexTTS2Provider(
            model_dir=tts_cfg.get("indextts_model_dir"),
            use_fp16=tts_cfg.get("use_fp16", True),
            device=tts_cfg.get("device"),
            version=version,
            duration_factor=tts_cfg.get("duration_factor", 1.0),
            lang=tts_cfg.get("lang", "zh"),
            use_qwen_emo=tts_cfg.get("use_qwen_emo"),
            emotion_mode=tts_cfg.get("emotion_mode", "text"),
            emo_alpha=tts_cfg.get("emo_alpha", 1.0),
        )
    raise ValueError(f"未知的 TTS provider: {name}")


def ensure_reference_voice(character, out_dir, provider=None, text=None):
    """用 edge-tts 为角色生成一段参考音（mp3），返回路径。"""
    provider = provider or EdgeTTSProvider()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{character}.mp3")
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return path
    sample = text or f"我是{character}。这是一段用来确定音色的参考音频。"
    provider.synthesize(sample, character, path)
    return path
