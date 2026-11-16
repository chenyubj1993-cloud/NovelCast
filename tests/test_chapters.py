import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.novel_reader import split_chapters


def test_light_novel_headings():
    text = "\n".join([
        "序章 起始",
        "序章正文。",
        "【第一问】",
        "第一问正文。",
        "【第二问】",
        "第二问正文。",
        "后记",
        "后记正文。",
    ])
    chapters = split_chapters(text)
    assert [c.title for c in chapters] == ["序章 起始", "【第一问】", "【第二问】", "后记"]
    assert "第一问正文。" in chapters[1].text


def test_bracket_dialogue_is_not_a_chapter():
    text = "\n".join([
        "第一章 开始",
        "正文。",
        "【Spaget___】",
        "这行是强调，不是标题。",
        "【就、就是说啊……好像会有什么东西突然跑出来……】",
        "还在第一章。",
    ])
    chapters = split_chapters(text)
    assert len(chapters) == 1
    assert "Spaget" in chapters[0].text


def test_chinese_number_headings():
    text = "\n".join(["第一回 楔子", "甲。", "第二回 相遇", "乙。"])
    chapters = split_chapters(text)
    assert [c.title for c in chapters] == ["第一回 楔子", "第二回 相遇"]
