# -*- coding: utf-8 -*-
"""coverage_analyzer 单元测试：覆盖率计算与报告输出。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import coverage_analyzer
from novelcast.coverage_analyzer import (
    analyze_coverage,
    print_coverage_report,
    print_summary,
)
from novelcast.dialogue_splitter import DialogueLine


def _line(text, character="旁白", emotion="neutral"):
    return DialogueLine(character=character, text=text, emotion=emotion)


class _Recorder:
    """替换模块级 log，直接记录消息，避免依赖 logging/stdout 捕获。"""

    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)


def _capture_log(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(coverage_analyzer, "log", recorder)
    return recorder



# ============================================================
# analyze_coverage
# ============================================================

def test_exact_coverage():
    report = analyze_coverage(
        "你好，世界。",
        [_line("你好，"), _line("世界。")],
        chapter_title="第一章",
    )

    assert report.chapter_title == "第一章"
    assert report.coverage == 1.0
    assert report.is_fully_covered is True
    assert report.lost_chars == 0
    assert report.lost_parts == []
    assert report.segments_count == 2
    assert report.original_len == len("你好，世界。")
    assert report.reconstructed_len == len("你好，世界。")


def test_whitespace_is_ignored_in_coverage():
    report = analyze_coverage("第一行\n第二行", [_line("第一行第二行")])

    assert report.coverage == 1.0
    assert report.is_fully_covered is True
    assert report.lost_chars == 0


def test_missing_text_is_reported():
    original = "甲乙丙丁戊己庚辛"
    report = analyze_coverage(original, [_line("甲乙丙丁")])

    assert report.coverage == 0.5
    assert report.lost_ratio == 0.5
    assert report.lost_chars == 4
    assert report.is_fully_covered is False
    assert [part["type"] for part in report.lost_parts] == ["开头", "结尾"]


def test_empty_original():
    report = analyze_coverage("", [])

    # 空章节没有内容可丢，语义上是「完全覆盖」，否则 coverage 与 fully_covered 矛盾
    assert report.coverage == 1.0
    assert report.is_fully_covered is True
    assert report.lost_chars == 0
    assert report.segments_count == 0


# ============================================================
# 报告输出
# ============================================================

def test_print_summary_empty(monkeypatch):
    recorder = _capture_log(monkeypatch)

    print_summary([])

    assert len(recorder.messages) == 1
    assert "没有覆盖率数据" in recorder.messages[0]


def test_print_summary_with_reports(monkeypatch):
    recorder = _capture_log(monkeypatch)
    reports = [
        analyze_coverage("甲乙丙丁", [_line("甲乙丙丁")], chapter_title="第一章"),  # 100%
        analyze_coverage("甲乙丙丁", [_line("甲乙")], chapter_title="第二章"),  # 50%
        analyze_coverage("甲乙丙丁戊己庚", [_line("甲乙丙丁戊己")], chapter_title="第三章"),  # 6/7 ≈ 85.7%
    ]

    print_summary(reports)

    messages = recorder.messages
    out = "\n".join(messages)
    assert "覆盖率汇总" in out
    assert "章节数: 3" in out
    assert "第一章" in out and "第三章" in out
    assert "优秀 (≥90%): 1章" in out
    assert "一般 (70-90%): 1章" in out
    assert "较差 (<70%): 1章" in out
    # 排名从低到高：50% 的第二章应排在 100% 的第一章之前
    second = next(i for i, m in enumerate(messages) if "第二章" in m)
    first = next(i for i, m in enumerate(messages) if "第一章" in m)
    assert second < first


def test_print_coverage_report_verbose_with_lost_parts(monkeypatch):
    recorder = _capture_log(monkeypatch)
    report = analyze_coverage(
        "甲乙丙丁戊己庚辛",
        [_line("甲乙丙丁")],
        chapter_title="第一章",
    )

    print_coverage_report(report, verbose=True)

    out = "\n".join(recorder.messages)
    assert "覆盖率分析: 第一章" in out
    assert "丢失详情" in out
    assert "[开头]" in out
    assert "❌ 原始文本未完全包含在拼接结果中" in out
