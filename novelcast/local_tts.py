# -*- coding: utf-8 -*-
"""用本地 IndexTTS-2（或 edge-tts）把剧本逐行合成为分段 wav，再拼成整章。

对外两个入口：
  synthesize_lines(lines, work_dir, ...) -> {idx: seg_path}
  synthesize_chapter(script_path, output_wav, ...) -> 整章 wav
"""
import hashlib
import json
import os
import re
import sys
import time

from novelcast.log import log
from novelcast.pronunciation import (
    apply_pronunciation,
)
from novelcast.pronunciation import (
    enabled_for as _pron_enabled,
)
from novelcast.pronunciation import (
    mapping_version as _pron_version,
)
from novelcast.tts_providers import (
    DEFAULT_EDGE_VOICE,
    EDGE_VOICE_MAP,
    EdgeTTSProvider,
    build_provider,
)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SILENCE_SECONDS = 0.3
SILENCE_NARRATION = 0.4  # 旁白段之后留一点气口
SILENCE_DIALOGUE = 0.15  # 连续对白之间不要拖
TARGET_LUFS = -18.0  # 有声书常用响度；再往上会被峰值保护挡住，反而失真
SAMPLE_RATE = 24000


def load_script(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("lines") or data.get("dialogues") or []
    return data


def _gender_of_voice(voice):
    try:
        from novelcast.cast_manager import GENDER_VOICES, load_voice_bank

        for gender, voices in GENDER_VOICES.items():
            if voice in voices:
                return gender
        bank = load_voice_bank()
        if bank:
            for item in bank.get("voices", []):
                if (item.get("id") or item.get("name")) == voice:
                    return item.get("gender", "unknown")
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _find_ref(refs_dir, *names):
    """按名字找参考音，wav 优先（voice bank），其次 mp3（edge 生成的）。"""
    for name in names:
        if not name:
            continue
        for ext in (".wav", ".mp3"):
            path = os.path.join(refs_dir, f"{name}{ext}")
            if os.path.exists(path) and os.path.getsize(path) > 2000:
                return path
    return None


def resolve_reference(character, cast, refs_dir, edge=None):
    """给角色挑一段参考音：角色名 > cast 里的音色名（voice bank）> edge 现生成。"""
    cast = cast or {}
    voices = cast.get("voices") or {}
    voice = voices.get(character) or cast.get("narrator") or DEFAULT_EDGE_VOICE
    # cast 指定的音色优先（voice bank 的 wav），没有再退回按角色名命名的旧参考音
    path = _find_ref(refs_dir, voice) or _find_ref(refs_dir, character)
    if path:
        return path
    # 没有现成参考音：先定一个目标文件，再让 edge 现生成
    path = os.path.join(refs_dir, f"{voice}.mp3")

    edge = edge or EdgeTTSProvider()
    edge_voice = EDGE_VOICE_MAP.get(character)
    if not edge_voice:
        gender = _gender_of_voice(voice)
        pool = {
            "female": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-XiaochenNeural"],
            "male": ["zh-CN-YunxiNeural", "zh-CN-YunyangNeural", "zh-CN-YunyeNeural"],
            "unknown": [DEFAULT_EDGE_VOICE],
        }[gender]
        edge_voice = pool[sum(map(ord, character)) % len(pool)]

    sample = f"我是{character}。这是一段用来确定音色的参考音频，希望你喜欢。"
    try:
        edge.synthesize(sample, edge_voice, path)
    except Exception as exc:  # noqa: BLE001
        log.info(f"    ⚠️ 参考音生成失败（{character}/{edge_voice}）: {exc}")
        fallback = os.path.join(refs_dir, "旁白.mp3")
        if os.path.exists(fallback):
            import shutil

            shutil.copyfile(fallback, path)
            log.info("    ↪ 临时借用旁白参考音")
        else:
            # 连旁白参考音都没有时，用默认音色再合成一次，保证流程不中断
            edge.synthesize(sample, DEFAULT_EDGE_VOICE, path)
    return path


MANIFEST_NAME = "segments.json"
MAX_SEGMENT_CHARS = 40


def split_text_for_tts(text, max_chars=MAX_SEGMENT_CHARS):
    """把过长的旁白/对白切成 <= max_chars 的小段，优先按句切，其次按逗号，最后硬切。

    返回的各段拼接后与原文（去掉首尾空白）完全一致，保证不丢字。
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []

    sentences = re.findall(r"[^。！？!?；;\n]*[。！？!?；;\n]+|[^。！？!?；;\n]+$", text)
    chunks = []
    buf = ""
    for sent in sentences:
        if len(buf) + len(sent) <= max_chars:
            buf += sent
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(sent) <= max_chars:
            buf = sent
            continue
        # 单句仍然超长：先按逗号/顿号/冒号切
        clauses = re.findall(r"[^，,、：:]*[，,、：:]+|[^，,、：:]+$", sent)
        for clause in clauses:
            if len(buf) + len(clause) <= max_chars:
                buf += clause
                continue
            if buf:
                chunks.append(buf)
                buf = ""
            while len(clause) > max_chars:
                chunks.append(clause[:max_chars])
                clause = clause[max_chars:]
            buf = clause
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def _sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_manifest(work_dir):
    path = os.path.join(work_dir, MANIFEST_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "items": {}}


def _save_manifest(work_dir, data):
    path = os.path.join(work_dir, MANIFEST_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _valid_wav(path):
    try:
        import soundfile as sf

        info = sf.info(path)
        return info.frames > 0 and info.samplerate > 0
    except Exception:  # noqa: BLE001
        return False


def synthesize_lines(
    lines,
    work_dir,
    cast=None,
    refs_dir=None,
    provider=None,
    config=None,
    limit=None,
    verbose=True,
    restart=False,
    units_out=None,
):
    """逐行合成到 work_dir/seg_XXXX.wav，返回 {原始索引: 路径}。

    断点续跑：segments.json 记录每段的 (text, character, emotion) 指纹，
    只有指纹一致且 wav 完整时才跳过；否则重合成。每段写完即落清单，进程被杀也不丢进度。
    """
    os.makedirs(work_dir, exist_ok=True)
    refs_dir = refs_dir or os.path.join(_PROJECT_ROOT, "output", "_refs")
    os.makedirs(refs_dir, exist_ok=True)
    provider = provider or build_provider(config)
    edge = EdgeTTSProvider()

    manifest = {"version": 1, "items": {}} if restart else _load_manifest(work_dir)
    total = len(lines) if not limit else min(limit, len(lines))

    # 先把每行展开成 <=MAX_SEGMENT_CHARS 的小段：长旁白一次合成会非常慢（实测单段可达 900–1700s）
    use_pron = _pron_enabled(config)
    pron_ver = _pron_version() if use_pron else ""
    if use_pron and pron_ver != "none":
        log.info("🔤 已启用多音字标注（config/pronunciation.json）")
    units = []
    for line in lines[:total]:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        character = line.get("character") or "旁白"
        emotion = line.get("emotion") or ""
        voice = line.get("voice_id") or (cast or {}).get("voices", {}).get(character, "")
        for part in split_text_for_tts(text):
            units.append(
                {
                    "text": apply_pronunciation(part) if use_pron else part,
                    "raw": part,
                    "character": character,
                    "emotion": emotion,
                    "voice": voice,
                }
            )

    if units_out is not None:
        units_out.extend(units)

    done = {}
    cached = 0
    t0 = time.time()
    # 模型标识进指纹：换 2.0/2.5、换模型目录、改语速/情绪模式后，旧分段不会被误复用
    model_tag = "{}|{}|{}|{}|{}|{}".format(
        getattr(provider, "version", ""),
        os.path.basename(str(getattr(provider, "model_dir", "") or "")),
        getattr(provider, "duration_factor", ""),
        getattr(provider, "lang", ""),
        getattr(provider, "emotion_mode", ""),
        getattr(provider, "emo_alpha", ""),
    )
    for k, unit in enumerate(units):
        text = unit["text"]
        character = unit["character"]
        emotion = unit["emotion"]
        voice = unit.get("voice", "")
        seg_path = os.path.join(work_dir, f"seg_{k:04d}.wav")
        # 音色也进指纹：换 cast / 换 voice bank 后不会把旧音色的分段当成命中
        key = _sha1("\x00".join([text, character, emotion, voice, model_tag]))
        rec = manifest["items"].get(str(k)) or {}
        if (
            not restart
            and rec.get("sha") == key
            and os.path.exists(seg_path)
            and _valid_wav(seg_path)
        ):
            cached += 1
            done[k] = seg_path
            continue
        ref = resolve_reference(character, cast, refs_dir, edge=edge)
        tmp_path = seg_path + ".part"
        provider.synthesize(
            text,
            ref,
            tmp_path,
            emotion=emotion if emotion not in ("", "平静", "neutral") else None,
        )
        os.replace(tmp_path, seg_path)  # 原子替换，避免半截 wav 被当成完成
        manifest["items"][str(k)] = {"sha": key, "character": character, "emotion": emotion}
        _save_manifest(work_dir, manifest)
        done[k] = seg_path
        if verbose:
            log.info(f"  [{k + 1}/{len(units)}] {character} | {unit.get('raw', text)[:20]} -> {os.path.getsize(seg_path) // 1024}KB {time.time() - t0:.0f}s")
    if verbose and cached:
        log.info(f"  ♻️ 断点续跑：复用 {cached}/{len(units)} 段缓存，本次合成 {len(units) - cached} 段")
    if verbose and len(units) > total:
        log.info(f"  ✂️ 长句拆分：{total} 行 -> {len(units)} 段（单段上限 {MAX_SEGMENT_CHARS} 字）")
    return done


def _measure_loudness(y, sample_rate):
    """积分响度（LUFS）；没装 pyloudnorm 时退回 RMS 近似。"""
    import numpy as np

    try:
        import pyloudnorm as pyln

        return float(pyln.Meter(sample_rate).integrated_loudness(y))
    except Exception:  # noqa: BLE001
        rms = float(np.sqrt(np.mean(y ** 2))) if y.size else 0.0
        return 20.0 * np.log10(rms) - 0.7 if rms > 0 else -70.0


def concat_segments(seg_paths, output_wav, characters=None, silence=None,
                    sample_rate=SAMPLE_RATE, target_lufs=TARGET_LUFS,
                    silence_narration=SILENCE_NARRATION, silence_dialogue=SILENCE_DIALOGUE,
                    stats=None):
    """拼接分段并做整章响度归一。

    characters 给出每段的角色：连续两段都是对白时用 0.15s 间隔，
    否则用 0.4s，避免"为什么？"和"他不得不接受。"之间也停半秒。
    响度先按 LUFS 归一到 target_lufs，再做峰值保护（不超过 0.95）。
    """
    import wave

    import numpy as np
    import soundfile as sf
    import soxr

    os.makedirs(os.path.dirname(output_wav) or ".", exist_ok=True)
    chunks = []
    seg_secs = []
    for seg in seg_paths:
        data, sr = sf.read(seg, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != sample_rate:
            data = soxr.resample(data, sr, sample_rate, quality="HQ")
        peak = float(np.abs(data).max()) if data.size else 0.0
        if peak > 1.5:  # IndexTTS 输出是 int16 量纲，先拉回 -1~1
            data = data / 32768.0
        chunks.append(data)
        seg_secs.append(len(data) / float(sample_rate))

    merged = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
    loud = _measure_loudness(merged, sample_rate)
    gain = 10.0 ** ((target_lufs - loud) / 20.0) if loud > -70 else 1.0
    peak = float(np.abs(merged).max()) if merged.size else 0.0
    if peak > 0 and peak * gain > 0.95:
        gain = 0.95 / peak

    tmp_wav = output_wav + ".part"
    with wave.open(tmp_wav, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        for idx, data in enumerate(chunks):
            pcm = np.clip(data * gain, -1.0, 1.0)
            out.writeframes((pcm * 32767.0).astype("<i2").tobytes())
            if idx >= len(chunks) - 1:
                continue
            if silence is not None:
                gap = silence
            else:
                a = characters[idx] if characters and idx < len(characters) else "旁白"
                b = characters[idx + 1] if characters and idx + 1 < len(characters) else "旁白"
                gap = silence_dialogue if (a != "旁白" and b != "旁白") else silence_narration
            out.writeframes(b"\x00\x00" * int(sample_rate * gap))
    os.replace(tmp_wav, output_wav)  # 原子落盘：中途被杀不会留下半截成品
    if stats is not None:
        stats.update({
            "duration": len(merged) / float(sample_rate),
            "segments": len(chunks),
            "max_segment": max(seg_secs) if seg_secs else 0.0,
            "lufs": target_lufs,
            "gain_db": 20.0 * np.log10(gain) if gain > 0 else 0.0,
            "peak": float(np.abs(np.concatenate(chunks) * gain).max()) if chunks else 0.0,
        })
    return output_wav


def _keep_awake(enable):
    """合成期间阻止系统休眠（仅 Windows 有 API；其它平台直接跳过）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if enable else 0)
        )
    except Exception:  # noqa: BLE001
        pass


def synthesize_chapter(
    script_path,
    output_wav,
    cast=None,
    refs_dir=None,
    provider=None,
    config=None,
    limit=None,
    silence=None,
    verbose=True,
    restart=False,
):
    _keep_awake(True)
    lines = load_script(script_path)
    if limit:
        lines = lines[:limit]
    if not lines:
        raise ValueError("剧本为空: " + script_path)

    work_dir = os.path.join(os.path.dirname(output_wav), "_segments")
    t0 = time.time()
    units = []
    done = synthesize_lines(
        lines, work_dir, cast=cast, refs_dir=refs_dir, provider=provider,
        config=config, limit=limit, verbose=verbose, restart=restart,
        units_out=units,
    )
    paths = [done[i] for i in sorted(done)]
    characters = [units[i]["character"] for i in sorted(done)] if units else None
    concat_segments(paths, output_wav, characters=characters, silence=silence)
    if verbose:
        log.info(f"done {len(paths)} segments in {time.time() - t0:.1f}s -> {output_wav} ({os.path.getsize(output_wav) // 1024}KB)")
    _keep_awake(False)
    return output_wav


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("script")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--cast")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cast = json.load(open(args.cast, encoding="utf-8")) if args.cast else None
    synthesize_chapter(args.script, args.output, cast=cast, limit=args.limit)
