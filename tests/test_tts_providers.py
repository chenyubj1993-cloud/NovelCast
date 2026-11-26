# -*- coding: utf-8 -*-
"""tts_providers 离线单元测试：音色解析、provider 构建、语速换算、情绪提示与空文本保护。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.local_tts import synthesize_lines
from novelcast.tts_providers import (
    DEFAULT_EDGE_VOICE,
    EDGE_VOICE_MAP,
    EMOTION_PROMPTS,
    EdgeTTSProvider,
    IndexTTS2Provider,
    OpenAITTSProvider,
    build_provider,
)


class Cfg:
    def __init__(self, config):
        self.config = config


class FakeTTS:
    def __init__(self, captured):
        self.captured = captured

    def infer(self, **kwargs):
        self.captured.update(kwargs)


class FakeProvider:
    """只记录调用、写一个占位文件（避免 synthesize_lines 的原子替换失败）。"""

    name = "edge"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice, output_path, emotion=None):
        self.calls.append({"text": text, "voice": voice, "output": output_path})
        Path(output_path).write_bytes(b"RIFF" + b"\x00" * 8)
        return output_path


def _emotion_provider(mode="text"):
    provider = IndexTTS2Provider(version="2.5", duration_factor=1.0, emotion_mode=mode)
    captured = {}
    provider._tts = FakeTTS(captured)
    provider._emo_ok = True
    return provider, captured


def test_every_edge_voice_map_name_resolves_to_azure_voice():
    edge = EdgeTTSProvider()
    assert len(EDGE_VOICE_MAP) >= 20
    for name, voice in EDGE_VOICE_MAP.items():
        assert edge.resolve_voice(name) == voice
        assert voice.startswith("zh-CN-"), (name, voice)


def test_resolve_voice_keeps_explicit_names_and_falls_back_for_unknown():
    edge = EdgeTTSProvider()
    assert edge.resolve_voice("zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"
    assert edge.resolve_voice("en-US-AriaNeural") == "en-US-AriaNeural"
    assert edge.resolve_voice("") == DEFAULT_EDGE_VOICE
    assert edge.resolve_voice(None) == DEFAULT_EDGE_VOICE
    assert edge.resolve_voice("不存在的角色") == DEFAULT_EDGE_VOICE


def test_custom_voice_map_overrides_without_mutating_global_map():
    edge = EdgeTTSProvider(voice_map={"旁白": "zh-CN-XiaoxiaoNeural", "新角色": "zh-CN-YunxiaNeural"})
    assert edge.resolve_voice("旁白") == "zh-CN-XiaoxiaoNeural"
    assert edge.resolve_voice("新角色") == "zh-CN-YunxiaNeural"
    assert EDGE_VOICE_MAP["旁白"] == "zh-CN-YunjianNeural"


def test_build_provider_defaults_to_edge():
    provider = build_provider({"tts": {}})
    assert isinstance(provider, EdgeTTSProvider)
    assert provider.name == "edge"
    assert provider.rate == "+0%"
    # 也接受 ConfigManager 风格的对象
    assert build_provider(Cfg({"tts": {}})).name == "edge"


def test_build_provider_builds_cloud_provider_from_config():
    provider = build_provider(
        Cfg(
            {
                "tts": {
                    "provider": "openai",
                    "cloud_base_url": "https://api.example.com/v1/",
                    "cloud_api_key": "secret-key",
                    "cloud_model": "tts-1",
                    "duration_factor": 0.8,
                }
            }
        )
    )
    assert isinstance(provider, OpenAITTSProvider)
    assert provider.kind == "cloud"
    assert provider.base_url == "https://api.example.com/v1"
    assert provider.model == "tts-1"
    assert provider.response_format == "wav"
    assert provider.instructions is True
    assert abs(provider.speed - 1.25) < 1e-9


def test_build_provider_rejects_unknown_and_missing_cloud_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="未知的 TTS provider"):
        build_provider({"tts": {"provider": "not-a-provider"}})
    with pytest.raises(ValueError, match="api_key"):
        build_provider({"tts": {"provider": "openai", "cloud_base_url": "https://x", "cloud_api_key": ""}})


def test_duration_factor_is_converted_to_edge_rate():
    assert build_provider({"tts": {"provider": "edge", "duration_factor": 1.0}}).rate == "+0%"
    assert build_provider({"tts": {"provider": "edge", "duration_factor": 0.9}}).rate == "+11%"
    assert build_provider({"tts": {"provider": "edge", "duration_factor": 1.1}}).rate == "-9%"


def test_emotion_prompt_mapping_for_known_and_custom_emotions():
    assert set(EMOTION_PROMPTS) == {"happy", "sad", "angry", "fear", "surprise", "disgust"}
    for emotion, prompt in EMOTION_PROMPTS.items():
        provider, captured = _emotion_provider()
        provider.synthesize("测试", "ref.wav", "out.wav", emotion=emotion)
        assert captured["use_emo_text"] is True
        assert captured["emo_text"] == prompt

    provider, captured = _emotion_provider()
    provider.synthesize("测试", "ref.wav", "out.wav", emotion="custom")
    assert captured["emo_text"] == "custom"


def test_neutral_emotion_sends_no_prompt():
    provider, captured = _emotion_provider()
    provider.synthesize("测试", "ref.wav", "out.wav", emotion="neutral")
    assert "use_emo_text" not in captured
    provider.synthesize("测试", "ref.wav", "out.wav", emotion="平静")
    assert "use_emo_text" not in captured


def test_synthesize_lines_skips_pure_punctuation(tmp_path):
    provider = FakeProvider()
    units = []
    done = synthesize_lines(
        [{"text": "……——！！", "character": "旁白"}],
        str(tmp_path / "work"),
        refs_dir=str(tmp_path / "refs"),
        provider=provider,
        units_out=units,
    )
    assert done == {}
    assert units == []
    assert provider.calls == []


def test_synthesize_lines_splits_long_line_by_max_segment_chars(tmp_path):
    provider = FakeProvider()
    units = []
    text = "甲" * 25
    done = synthesize_lines(
        [{"text": text, "character": "旁白", "emotion": "neutral"}],
        str(tmp_path / "work"),
        refs_dir=str(tmp_path / "refs"),
        provider=provider,
        config=Cfg({"tts": {"max_segment_chars": 10}}),
        units_out=units,
    )
    assert len(units) == 3
    assert all(len(u["raw"]) <= 10 for u in units)
    assert "".join(u["raw"] for u in units) == text
    assert len(done) == len(units)
