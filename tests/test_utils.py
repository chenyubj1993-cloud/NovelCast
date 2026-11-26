# -*- coding: utf-8 -*-
"""utils 单元测试：安全文件名、WAV 时长与时长格式化。"""

import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.utils import format_duration, get_wav_duration, safe_filename

# ============================================================
# safe_filename
# ============================================================

def test_safe_filename_replaces_illegal_chars():
    assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_safe_filename_strips_dots_and_whitespace():
    assert safe_filename("  ..章节标题.. ") == "章节标题"
    assert safe_filename("") == "untitled"
    assert safe_filename("   ") == "untitled"


def test_safe_filename_limits_length():
    assert safe_filename("字" * 200, max_len=10) == "字" * 10
    assert len(safe_filename("字" * 200)) == 80


# ============================================================
# get_wav_duration
# ============================================================

def _write_wav(path, seconds=1.0, rate=24000):
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x00" * frames)


def test_get_wav_duration_generated_wav(tmp_path):
    path = tmp_path / "one_second.wav"
    _write_wav(path, seconds=1.0)

    assert get_wav_duration(str(path)) == pytest.approx(1.0)


def test_get_wav_duration_missing_or_invalid(tmp_path):
    assert get_wav_duration(str(tmp_path / "missing.wav")) == 0.0

    bogus = tmp_path / "bogus.wav"
    bogus.write_text("not a wav", encoding="utf-8")
    assert get_wav_duration(str(bogus)) == 0.0


# ============================================================
# format_duration
# ============================================================

def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(59.9) == "0:59"
    assert format_duration(225) == "3:45"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3750) == "1:02:30"
    assert format_duration(-5) == "0:00"
