# -*- coding: utf-8 -*-
"""local_tts 离线单元测试：文本切分、分段长度、音频校验与拼接。"""

import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import local_tts


class Cfg:
    def __init__(self, config):
        self.config = config


def _tone(path, seconds=0.2, freq=220.0, sample_rate=local_tts.SAMPLE_RATE):
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    data = 0.2 * np.sin(2 * np.pi * freq * t)
    sf.write(str(path), data, sample_rate, subtype="PCM_16")
    return path


SAMPLES = [
    "你好。今天天气不错！我们去公园吧？",
    "第一段。\n\n第二段，有逗号；还有分号。",
    "Hello world. This is a test! Does it split?",
    "甲" * 95,
    "他走得很快，像一阵风——没人追得上。",
]


def test_split_text_for_tts_is_lossless_for_samples():
    for text in SAMPLES:
        parts = local_tts.split_text_for_tts(text, 40)
        assert parts, text
        assert "".join(parts) == text.strip()


def test_split_text_for_tts_respects_max_chars():
    for text in SAMPLES:
        for max_chars in (40, 15):
            parts = local_tts.split_text_for_tts(text, max_chars)
            assert all(len(p) <= max_chars for p in parts), (text, max_chars, [len(p) for p in parts])
            assert "".join(parts) == text.strip()


def test_split_text_for_tts_handles_blank_and_short_text():
    assert local_tts.split_text_for_tts("") == []
    assert local_tts.split_text_for_tts("   \n  ") == []
    assert local_tts.split_text_for_tts("你好。") == ["你好。"]


def test_resolve_max_segment_chars_by_provider_and_override():
    assert local_tts.resolve_max_segment_chars(None, SimpleNamespace(name="indextts2")) == 40
    assert local_tts.resolve_max_segment_chars(None, SimpleNamespace(name="indextts2.5")) == 40
    assert local_tts.resolve_max_segment_chars(None, SimpleNamespace(name="edge")) == 120
    assert local_tts.resolve_max_segment_chars(Cfg({"tts": {"provider": "indextts2"}}), None) == 40
    assert local_tts.resolve_max_segment_chars(Cfg({"tts": {"provider": "openai"}}), None) == 120
    # 显式配置优先，且下限为 10
    assert local_tts.resolve_max_segment_chars(Cfg({"tts": {"max_segment_chars": 25}}), SimpleNamespace(name="edge")) == 25
    assert local_tts.resolve_max_segment_chars(Cfg({"tts": {"max_segment_chars": 3}}), SimpleNamespace(name="indextts2")) == 10


def test_valid_audio_rejects_short_and_missing_files(tmp_path):
    short = _tone(tmp_path / "short.wav", seconds=0.2)
    full = _tone(tmp_path / "full.wav", seconds=1.2)
    assert local_tts._valid_audio(str(short)) is False
    assert local_tts._valid_audio(str(full)) is True
    assert local_tts._valid_audio(str(short), min_seconds=0.1) is True
    assert local_tts._valid_audio(str(tmp_path / "missing.wav")) is False


def test_concat_segments_builds_wav_with_expected_duration(tmp_path):
    segs = [
        _tone(tmp_path / f"seg{i}.wav", freq=220.0 + i * 40) for i in range(3)
    ]
    stats = {}
    out = tmp_path / "merged.wav"
    local_tts.concat_segments(
        [str(p) for p in segs],
        str(out),
        characters=["旁白", "叶秋", "苏沐橙"],
        stats=stats,
    )

    assert out.exists()
    with wave.open(str(out), "rb") as f:
        assert f.getframerate() == local_tts.SAMPLE_RATE
        assert f.getsampwidth() == 2
        frames = f.getnframes()
    # 3 × 0.2s + 旁白后 0.4s + 对白后 0.15s = 1.15s
    assert abs(frames / local_tts.SAMPLE_RATE - 1.15) < 0.02
    assert stats["segments"] == 3
    assert abs(stats["duration"] - 1.15) < 0.02
    assert abs(stats["max_segment"] - 0.2) < 0.02
    assert "lufs" in stats and "gain_db" in stats and "peak" in stats


def test_concat_segments_honours_explicit_silence(tmp_path):
    segs = [_tone(tmp_path / "a.wav"), _tone(tmp_path / "b.wav")]
    stats = {}
    local_tts.concat_segments(
        [str(p) for p in segs],
        str(tmp_path / "out.wav"),
        silence=0.05,
        stats=stats,
    )
    # 0.2 + 0.05 + 0.2 = 0.45
    assert abs(stats["duration"] - 0.45) < 0.02
