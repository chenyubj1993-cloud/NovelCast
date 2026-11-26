# -*- coding: utf-8 -*-
"""novel_reader 单元测试：TXT 读取（UTF-8 / GBK / BOM）与章节分割规则。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import novel_reader
from novelcast.novel_reader import read_novel, split_chapters

# ============================================================
# read_novel / _read_txt
# ============================================================

def test_read_txt_utf8(tmp_path):
    path = tmp_path / "测试书.txt"
    path.write_text("第一章 开始\n你好，世界。", encoding="utf-8")

    book_name, content = read_novel(str(path))

    assert book_name == "测试书"
    assert content == "第一章 开始\n你好，世界。"


def test_read_txt_gbk(tmp_path):
    path = tmp_path / "gbk书.txt"
    path.write_bytes("第一章 开始\n这是GBK编码的正文。".encode("gbk"))

    book_name, content = read_novel(str(path))

    assert book_name == "gbk书"
    assert "这是GBK编码的正文" in content


def test_read_txt_strips_bom(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "第一章 开始\n带BOM的正文。".encode("utf-8"))

    _, content = read_novel(str(path))

    assert not content.startswith("\ufeff")
    assert content.startswith("第一章")


def test_read_novel_relative_path_uses_input_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(novel_reader, "INPUT_DIR", tmp_path)
    (tmp_path / "相对书.txt").write_text("正文。", encoding="utf-8")

    book_name, content = read_novel("相对书.txt")

    assert book_name == "相对书"
    assert content == "正文。"


def test_read_novel_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(novel_reader, "INPUT_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="文件不存在"):
        read_novel("不存在的书.txt")


def test_read_novel_unsupported_suffix(tmp_path):
    path = tmp_path / "书.md"
    path.write_text("正文", encoding="utf-8")

    with pytest.raises(ValueError, match="不支持的文件格式"):
        read_novel(str(path))


# ============================================================
# split_chapters
# ============================================================

def test_split_chapters_di_x_zhang():
    text = "第一章 起点\n正文一。\n第二章 终点\n正文二。"

    chapters = split_chapters(text)

    assert [c.title for c in chapters] == ["第一章 起点", "第二章 终点"]
    assert [c.number for c in chapters] == [1, 2]
    assert "正文一。" in chapters[0].text
    assert "正文二。" in chapters[1].text


def test_split_chapters_light_novel_headings():
    text = "\n".join([
        "序章 起始", "序章正文。",
        "【第一问】", "第一问正文。",
        "第一章 标题", "章正文。",
    ])

    chapters = split_chapters(text)

    assert [c.title for c in chapters] == ["序章 起始", "【第一问】", "第一章 标题"]
    assert "第一问正文。" in chapters[1].text
    assert [c.number for c in chapters] == [1, 2, 3]


def test_split_chapters_drops_template_page_lines():
    text = "\n".join([
        "第一章 开始",
        "title.xhtml",
        "这个文件不要做任何改动",
        "书名在title.xhtml",
        "真正的正文。",
    ])

    chapters = split_chapters(text)

    assert len(chapters) == 1
    assert chapters[0].title == "第一章 开始"
    assert chapters[0].text == "真正的正文。"


def test_split_chapters_merges_pseudo_chapters():
    body = "正文" * 120
    text = f"封面\n版权\n\n第一章 开始\n{body}\n第二章 继续\n{body}"

    chapters = split_chapters(text)

    assert [c.title for c in chapters] == ["第一章 开始", "第二章 继续"]
    assert "封面" in chapters[0].text and "版权" in chapters[0].text
    assert [c.number for c in chapters] == [1, 2]


def test_split_chapters_without_headings_is_single_chapter():
    chapters = split_chapters("只是一段普通正文。")

    assert len(chapters) == 1
    assert chapters[0].title == "全文"
    assert chapters[0].text == "只是一段普通正文。"
