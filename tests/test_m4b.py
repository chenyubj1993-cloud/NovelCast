import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import m4b


def test_chapter_marks_accumulate():
    marks = m4b.chapter_marks([1.0, 2.5, 0.25], ["一", "二", "三"])
    assert [m["start_ms"] for m in marks] == [0, 1000, 3500]
    assert [m["end_ms"] for m in marks] == [1000, 3500, 3750]


def test_ffmetadata_escapes_and_contains_chapters():
    marks = m4b.chapter_marks([1.0], ["第一章 = 开始; #1"])
    text = m4b.ffmetadata_text(marks, title="某本书", artist="某人")
    assert text.startswith(";FFMETADATA1\n")
    assert "title=某本书" in text
    assert "artist=某人" in text
    assert "[CHAPTER]" in text
    assert "START=0" in text and "END=1000" in text
    assert "\\=" in text and "\\;" in text and "\\#" in text


def test_missing_ffmpeg_raises_helpful_error(monkeypatch):
    monkeypatch.setattr(m4b.shutil, "which", lambda name: None)
    with pytest.raises(m4b.M4BError) as exc:
        m4b.build_m4b([Path("a.wav")], ["一"], Path("out.m4b"))
    assert "ffmpeg" in str(exc.value)
