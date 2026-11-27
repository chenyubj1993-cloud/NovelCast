"""
配置管理模块
负责加载、保存和管理所有配置项
"""

import copy
import json
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Optional

from novelcast.log import log

# ============================================================
# 项目路径配置
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
CONFIG_DIR = PROJECT_ROOT / "config"
LLM_RAW_DIR = PROJECT_ROOT / "llm_raw_responses"

# 确保目录存在
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)
LLM_RAW_DIR.mkdir(exist_ok=True)


# ============================================================
# 默认配置
# ============================================================
DEFAULT_CONFIG = {
    # 输出根目录（相对路径按项目根解析；每本书会建「<书名>_有声书」子目录）
    "output_dir": "output",  # 输出根目录（--output 优先于它，相对路径按项目根解析）
    "roster_mode": "full",  # full | off：off 跳过全书角色表预扫，边分边认角色（试听单章更快）

    # LLM API配置（用于对话分割）
    "llm_api": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",  # 需要用户配置
        "model": "deepseek-chat",
    },

    # TTS API配置（用于语音合成）
    "tts_api": {
        "base_url": "https://api.mimoai.com/v1",
        "api_key": "",  # 需要用户配置
        "model": "mimo-v2.5-pro",
    },

    # 生成参数
    "generation": {
        "chunk_size": 1500,  # LLM分割时的chunk大小
        "max_duration_per_file": 900,  # 单个音频文件最大时长（秒），默认15分钟
        "silence_between_segments": 0.5,  # 段落间静音时长（秒）
        "silence_between_chapters": 2.0,  # 章节间静音时长（秒）
        "min_split_length": 5,  # 最小分割长度，低于此长度的文本将被跳过
    },

    # 并发配置
    "concurrency": {
        "llm_concurrency": 3,  # LLM并发数
        "tts_concurrency": 5,  # TTS并发数
    },

    # 速率限制
    "rate_limit": {
        "llm_rpm": 30,  # LLM每分钟请求数
        "tts_rpm": 60,  # TTS每分钟请求数
    },

    # TTS配置
    "tts": {
        "provider": "edge",  # edge | indextts2 | indextts2.5 | openai（默认 edge：开箱即用，不需要下载模型）
        "max_chars": 300,  # 单次TTS最大字符数
        "min_chars": 2,  # 最小字符数，低于此值跳过
        "sample_rate": 24000,
        "channels": 1,
        "sample_width": 2,
        "indextts_model_dir": "models/IndexTTS-2.5",
        "use_fp16": True,
        "model_version": "2.5",  # 2 | 2.5（2.5 支持 <字|拼音> 发音标注与 duration_factor 变速）
        "duration_factor": 1.0,  # 仅 2.5：0.5~2.0，越小越快
        "lang": "zh",  # 仅 2.5：zh | en | ja | es | ar
        "use_qwen_emo": None,  # 仅 2.5：None 自动 / False 关闭文本情绪
        "emotion_mode": "text",  # text | vector | off：情绪用文字提示还是 8 维向量
        "emo_alpha": 0.55,  # 0~1，情绪强度（1 为最满；0.55 更克制，避免吵闹）
        "loudness_lufs": -18.0,  # 整章响度目标（LUFS）
        "silence_narration": 0.4,  # 旁白后停顿（秒）
        "silence_dialogue": 0.15,  # 连续对白之间停顿（秒）
        "max_segment_chars": None,  # 单段上限；None = 按 provider 自动（本地 2.5 为 40，edge/云端 120）
        "cloud_concurrency": 4,  # 云端/edge 合成并发数（本地 indextts2 始终串行，显存不够）
        "reference_dir": "output/_refs",
        "edge_voice_map": {},
        # 云端 TTS（OpenAI 兼容的 /audio/speech）
        "cloud_base_url": "",  # 留空则读 OPENAI_BASE_URL，再退回 OpenAI 官方
        "cloud_api_key": "",  # 留空则读 OPENAI_API_KEY
        "cloud_model": "gpt-4o-mini-tts",
        "cloud_format": "wav",
        "cloud_instructions": True,
        "cloud_speed": None,
        "cloud_voices": {
            "female": ["nova", "shimmer"],
            "male": ["onyx", "echo"],
            "unknown": ["alloy"],
        },
    },

    # 音色预设
    "voice_presets": {
        "冰糖": "冰糖",
        "苏打": "苏打",
        "茉莉": "茉莉",
        "白桦": "白桦",
        "Mia": "Mia",
        "Chloe": "Chloe",
        "Milo": "Milo",
        "Dean": "Dean",
        "default": "冰糖",
    },

    # 角色音色映射
    "character_voices": {
        "旁白": "冰糖",
        "默认": "冰糖",
    },

    # 情绪提示词
    "emotion_prompts": {
        "neutral": "用平静自然的语气朗读",
        "happy": "用开心愉悦的语气朗读",
        "sad": "用悲伤低沉的语气朗读",
        "angry": "用愤怒激动的语气朗读",
        "fear": "用恐惧紧张的语气朗读",
        "surprise": "用惊讶的语气朗读",
        "disgust": "用厌恶的语气朗读",
        "default": "用自然的语气朗读",
    },

    # LLM分割提示词
    "split_prompt": """你是一个专业的有声书剧本编辑。请将以下小说文本分割成独立的对话和旁白段落。

## 规则：
1. 每个段落要么是旁白，要么是单个角色的对话
2. 旁白的角色名固定为"旁白"
3. 对话的角色名必须是具体的人名或称谓（如：小明、妈妈、老师、张三）
4. **禁止使用以下类型作为角色名**：
   - 代词：他、她、它、我、你、我们、他们
   - 描述性词语：些调皮地、没好气地、开心地、生气地
   - 动作描述：说、道、喊、问、笑、哭
5. 如果无法确定具体角色，统一归为"旁白"
6. 保持原文内容完整，不要遗漏任何文字
7. 每个段落需要标注情绪（neutral/happy/sad/angry/fear/surprise/disgust）

## 已知角色映射（如果存在）：
{character_map}

## 输出JSON数组格式：
[
  {{"character": "角色名", "text": "对话内容", "emotion": "情绪"}},
  ...
]

## 文本内容：
{text}""",

    # 内容审核重试提示词
    "moderation_retry_prompt": """请将以下文本分割成更小的段落，每段不超过500字。

规则：
1. 保持原文内容完整
2. 在合适的句子边界处分割
3. 每个段落标注角色和情绪

输出JSON数组格式：
[
  {{"character": "角色名", "text": "内容", "emotion": "情绪"}},
  ...
]

文本内容：
{text}""",
}


@dataclass
class LlmApiConfig:
    """LLM API配置（用于对话分割）"""
    base_url: str = "https://api.mimoai.com/v1"
    api_key: str = ""
    model: str = "mimo-v2.5-pro"


@dataclass
class TtsApiConfig:
    """TTS API配置（用于语音合成）"""
    base_url: str = "https://api.mimoai.com/v1"
    api_key: str = ""
    model: str = "mimo-v2.5-pro"


@dataclass
class GenerationConfig:
    """生成参数配置"""
    chunk_size: int = 1500
    max_duration_per_file: int = 900
    silence_between_segments: float = 0.5
    silence_between_chapters: float = 2.0
    min_split_length: int = 5  # 最小分割长度，低于此长度的文本将被跳过


@dataclass
class ConcurrencyConfig:
    """并发配置"""
    llm_concurrency: int = 3
    tts_concurrency: int = 5


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    llm_rpm: int = 30
    tts_rpm: int = 60


@dataclass
class TtsConfig:
    """TTS配置"""
    provider: str = "edge"
    max_chars: int = 300
    min_chars: int = 2
    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2
    indextts_model_dir: str = "models/IndexTTS-2.5"
    use_fp16: bool = True
    model_version: str = "2.5"
    duration_factor: float = 1.0
    lang: str = "zh"
    use_qwen_emo: Optional[bool] = None
    emotion_mode: str = "text"
    emo_alpha: float = 0.55
    loudness_lufs: float = -18.0
    silence_narration: float = 0.4
    silence_dialogue: float = 0.15
    max_segment_chars: Optional[int] = None
    cloud_concurrency: int = 4
    reference_dir: str = "output/_refs"
    edge_voice_map: dict = field(default_factory=dict)
    cloud_base_url: str = ""
    cloud_api_key: str = ""
    cloud_model: str = "gpt-4o-mini-tts"
    cloud_format: str = "wav"
    cloud_instructions: bool = True
    cloud_speed: Optional[float] = None
    cloud_voices: dict = field(default_factory=dict)


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径，默认为 config/settings.json
        """
        if config_path is None:
            config_path = str(CONFIG_DIR / "settings.json")

        self.config_path = Path(config_path)
        # 必须深拷贝：浅拷贝会让所有实例共享 tts/llm_api 等嵌套 dict，
        # 另一个 ConfigManager 重新加载 settings.json 时会把 CLI 覆盖改回去。
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        # CLI -o / --output：显式指定输出目录时不再拼「书名_有声书」
        self.output_override: Optional[Path] = None

        # 加载配置文件
        self._load_config()

        # 初始化子配置对象
        self.llm_api = LlmApiConfig(**self.config.get("llm_api", {}))
        self.tts_api = TtsApiConfig(**self.config.get("tts_api", {}))
        self.generation = GenerationConfig(**self.config.get("generation", {}))
        self.concurrency = ConcurrencyConfig(**self.config.get("concurrency", {}))
        self.rate_limit = RateLimitConfig(**self.config.get("rate_limit", {}))
        tts_fields = {f.name for f in dataclass_fields(TtsConfig)}
        self.tts = TtsConfig(
            **{k: v for k, v in self.config.get("tts", {}).items() if k in tts_fields}
        )

    def _load_config(self):
        """加载配置文件"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8-sig') as f:
                    user_config = json.load(f)
                # 深度合并配置
                self._merge_config(self.config, user_config)
                log.info(f"✅ 已加载配置: {self.config_path}")
            except Exception as e:
                log.info(
                    f"⚠️ 配置文件加载失败，使用默认配置: {e}\n"
                    f"   请检查 {self.config_path} 的 JSON 语法"
                    "（常见原因：文件开头有 BOM、结尾多了逗号、中文引号）"
                )
        else:
            # 首次运行，保存默认配置
            self.save_config()
            log.info(f"✅ 已创建默认配置: {self.config_path}")

    def _merge_config(self, base: dict, override: dict):
        """深度合并配置"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            log.info(f"✅ 配置已保存: {self.config_path}")
        except Exception as e:
            log.info(f"❌ 配置保存失败: {e}")

    def apply_tts_overrides(self, **kwargs):
        """命令行覆盖 TTS 配置，例如 --tts edge --speed 0.95。"""
        tts = self.config.setdefault("tts", {})
        for key, value in kwargs.items():
            if value is None:
                continue
            tts[key] = value
            if hasattr(self.tts, key):
                setattr(self.tts, key, value)

    def get(self, key: str, default=None):
        """获取配置项（支持点号分隔的路径）"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value):
        """设置配置项（支持点号分隔的路径）"""
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def update_llm_api_key(self, api_key: str):
        """更新LLM API密钥"""
        self.config["llm_api"]["api_key"] = api_key
        self.llm_api.api_key = api_key
        self.save_config()

    def update_tts_api_key(self, api_key: str):
        """更新TTS API密钥"""
        self.config["tts_api"]["api_key"] = api_key
        self.tts_api.api_key = api_key
        self.save_config()

    def get_llm_raw_dir(self, book_name: str, chapter_name: str = None) -> Path:
        """获取LLM原始响应目录（按书名和章节分类）"""
        book_dir = LLM_RAW_DIR / self._safe_filename(book_name)
        if chapter_name:
            book_dir = book_dir / self._safe_filename(chapter_name)
        book_dir.mkdir(parents=True, exist_ok=True)
        return book_dir

    def get_output_dir(self, book_name: str) -> Path:
        """获取输出目录。

        优先级：--output 显式目录 > 配置 output_dir（相对路径按项目根解析）
        > 默认 output/。
        """
        if self.output_override:
            output_dir = Path(str(self.output_override)).expanduser()
            if not output_dir.is_absolute():
                output_dir = PROJECT_ROOT / output_dir
        else:
            root = Path(str(self.config.get("output_dir") or "output")).expanduser()
            if not root.is_absolute():
                root = PROJECT_ROOT / root
            output_dir = root / f"{self._safe_filename(book_name)}_有声书"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_temp_dir(self, book_name: str, chapter_num: int) -> Path:
        """获取临时文件目录"""
        output_dir = self.get_output_dir(book_name)
        temp_dir = output_dir / f"_temp_{chapter_num:03d}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @staticmethod
    def _safe_filename(name: str) -> str:
        """生成安全的文件名"""
        # 替换不安全的字符
        unsafe_chars = '<>:"/\\|?*'
        for char in unsafe_chars:
            name = name.replace(char, '_')
        # 限制长度
        if len(name) > 100:
            name = name[:100]
        return name.strip()


# 全局配置实例
_config_manager: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


