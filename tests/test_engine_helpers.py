# -*- coding: utf-8 -*-
"""engine 辅助函数离线单元测试：内容裁剪、安全文件名、覆盖率判定与剧本断点续跑。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import engine
from novelcast.dialogue_splitter import DialogueLine
from novelcast.engine import (
    ChapterSplitResult,
    _filter_chapters_content,
    _load_script_result,
    _roster_from_scripts,
    _save_script_result,
    split_chapter,
)
from novelcast.novel_reader import Chapter
from novelcast.utils import safe_filename


class Cfg:
    def __init__(self, config=None, output_dir=None):
        self.config = config or {}
        self.output_dir = Path(output_dir) if output_dir else None

    def get_output_dir(self, book_name):
        path = self.output_dir / f"{book_name}_有声书"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _patch_llm(monkeypatch, lines):
    async def fake_split(text, title, book_name, character_map=None):
        return lines

    monkeypatch.setattr(engine, "split_dialogues_async", fake_split)


def test_filter_chapters_content_truncates_chars_and_marks_partial():
    chapter = Chapter(number=1, title="第一章", text="甲" * 10 + "\n\n" + "乙" * 10 + "\n\n" + "丙" * 10)
    filtered = _filter_chapters_content([chapter], first_chars=25)

    assert len(filtered) == 1
    result = filtered[0]
    assert result.number == 1
    assert result.title == "第一章"
    # 段落分隔符也计入长度，所以结果可能略超 first_chars
    assert result.text == "甲" * 10 + "\n\n" + "乙" * 10 + "\n\n" + "丙" * 5
    assert len(result.text) > 25
    assert result.partial is True
    assert chapter.text.endswith("丙" * 10)  # 原对象未被修改


def test_filter_chapters_content_by_paragraphs_and_no_limit():
    chapter = Chapter(number=2, title="第二章", text="甲" * 10 + "\n\n" + "乙" * 10 + "\n\n" + "丙" * 10)
    by_paragraph = _filter_chapters_content([chapter], first_paragraphs=2)[0]
    assert by_paragraph.text == "甲" * 10 + "\n\n" + "乙" * 10
    assert by_paragraph.partial is True

    untouched = _filter_chapters_content([Chapter(number=3, title="短", text="很短")])[0]
    assert untouched.text == "很短"
    assert untouched.partial is False


def test_safe_filename_strips_invalid_characters_and_bounds_length():
    cleaned = safe_filename(' 第1章: 开始/结束? <完>|* "x" \n ')
    for bad in '\\/:*?"<>|\n\t':
        assert bad not in cleaned
    assert cleaned.startswith("第1章")
    assert safe_filename("x" * 200).__len__() == 80
    assert safe_filename("   ...   ") == "untitled"
    assert safe_filename(None) == "untitled"
    assert safe_filename("中文标题") == "中文标题"


def test_split_chapter_low_coverage_marks_failure(monkeypatch):
    chapter = Chapter(number=1, title="替换测试", text="甲" * 50)
    _patch_llm(monkeypatch, [DialogueLine(character="旁白", text="乙" * 50, emotion="neutral")])

    result = asyncio.run(split_chapter(chapter, "测试书", Cfg({"min_coverage": 0.7})))

    assert result.success is False
    assert result.coverage < 0.7
    assert result.error == ""
    assert len(result.lines) == 1


def test_split_chapter_full_coverage_succeeds(monkeypatch):
    text = "你好世界。" * 5
    chapter = Chapter(number=2, title="完整测试", text=text)
    _patch_llm(monkeypatch, [DialogueLine(character="旁白", text=text, emotion="neutral")])

    result = asyncio.run(split_chapter(chapter, "测试书", Cfg({"min_coverage": 0.7})))

    assert result.success is True
    assert result.coverage >= 0.99
    assert len(result.lines) == 1


def test_split_chapter_empty_llm_result_marks_failure(monkeypatch):
    chapter = Chapter(number=3, title="空结果", text="一些正文。")
    _patch_llm(monkeypatch, [])

    result = asyncio.run(split_chapter(chapter, "测试书", Cfg()))

    assert result.success is False
    assert result.error == "LLM返回空结果"
    assert result.lines == []


def test_save_and_load_script_roundtrip(tmp_path):
    text = "你好世界。" * 5
    chapter = Chapter(number=4, title="续跑: 测试/章节", text=text)
    result = ChapterSplitResult(
        chapter=chapter,
        lines=[DialogueLine(character="旁白", text=text, emotion="neutral", voice_id="zh-CN-YunxiNeural")],
        coverage=1.0,
        success=True,
    )
    config = Cfg(output_dir=tmp_path)

    script = _save_script_result(result, "测试书", config)
    assert script.exists()
    assert script.name == "004_续跑_ 测试_章节_script.json"

    loaded = _load_script_result(chapter, "测试书", config)
    assert loaded is not None
    assert loaded.success is True
    assert abs(loaded.coverage - 1.0) < 1e-9
    assert loaded.lines[0].character == "旁白"
    assert loaded.lines[0].voice_id == "zh-CN-YunxiNeural"


def test_load_script_rejects_partial_and_stale_source(tmp_path):
    config = Cfg(output_dir=tmp_path)

    partial_chapter = Chapter(number=5, title="半章", text="甲" * 20)
    partial_chapter.partial = True
    partial_result = ChapterSplitResult(
        chapter=partial_chapter,
        lines=[DialogueLine(character="旁白", text="甲" * 20, emotion="neutral")],
        coverage=1.0,
        success=True,
    )
    _save_script_result(partial_result, "测试书", config)
    full_chapter = Chapter(number=5, title="半章", text="甲" * 20)
    assert _load_script_result(full_chapter, "测试书", config) is None

    short_chapter = Chapter(number=6, title="源文变更", text="甲" * 10)
    _save_script_result(
        ChapterSplitResult(
            chapter=short_chapter,
            lines=[DialogueLine(character="旁白", text="甲" * 10, emotion="neutral")],
            coverage=1.0,
            success=True,
        ),
        "测试书",
        config,
    )
    changed_chapter = Chapter(number=6, title="源文变更", text="乙" * 500)
    assert _load_script_result(changed_chapter, "测试书", config) is None


def test_roster_from_scripts_picks_most_frequent_as_protagonist(tmp_path):
    config = Cfg(output_dir=tmp_path)
    ch1 = Chapter(number=1, title="一", text="正" * 30)
    ch2 = Chapter(number=2, title="二", text="正" * 30)
    _save_script_result(
        ChapterSplitResult(
            chapter=ch1,
            lines=[
                DialogueLine(character="旁白", text="正" * 10, emotion="neutral"),
                DialogueLine(character="旁白", text="正" * 10, emotion="neutral"),
                DialogueLine(character="叶秋", text="正" * 10, emotion="neutral"),
            ],
            coverage=1.0,
            success=True,
        ),
        "书",
        config,
    )
    _save_script_result(
        ChapterSplitResult(
            chapter=ch2,
            lines=[
                DialogueLine(character="苏沐橙", text="正" * 10, emotion="neutral"),
                DialogueLine(character="苏沐橙", text="正" * 10, emotion="neutral"),
                DialogueLine(character="苏沐橙", text="正" * 5, emotion="neutral"),
                DialogueLine(character="苏沐橙", text="正" * 5, emotion="neutral"),
                DialogueLine(character="旁白", text="正" * 10, emotion="neutral"),
            ],
            coverage=1.0,
            success=True,
        ),
        "书",
        config,
    )

    roster = _roster_from_scripts(config.get_output_dir("书"))
    characters = roster["characters"]
    assert characters["苏沐橙"]["role"] == "protagonist"
    assert characters["苏沐橙"]["appearances"] == 4
    assert characters["旁白"]["role"] == "minor"
    assert characters["旁白"]["appearances"] == 3
    assert characters["叶秋"]["appearances"] == 1
    assert roster["version"] == 1


def test_split_chapter_respects_configured_threshold(monkeypatch):
    text = "你好世界。" * 5
    chapter = Chapter(number=7, title="阈值", text=text)
    _patch_llm(monkeypatch, [DialogueLine(character="旁白", text=text, emotion="neutral")])

    result = asyncio.run(split_chapter(chapter, "书", Cfg({"min_coverage": 1.01})))

    assert result.coverage >= 0.99
    assert result.success is False
