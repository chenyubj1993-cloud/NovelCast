"""单元测试：剧本完整性校验（novelcast.script_qa）。"""

from __future__ import annotations

import pytest

from novelcast.dialogue_splitter import DialogueLine
from novelcast.script_qa import (
    alignment,
    dedupe_adjacent,
    format_gap,
    repair_attributions,
    repair_tail,
)


def line(text: str, character: str = "旁白") -> DialogueLine:
    return DialogueLine(character=character, text=text, emotion="neutral", voice_id="")


def test_alignment_ignores_punctuation_only_differences():
    # LLM 标注时通常会把对白引号去掉，并可能丢掉句末标点：不算丢字
    original = "他说：“你好。”然后走了。"
    lines = [line("他说你好"), line("然后走了")]

    report = alignment(original, lines)

    assert report["missing_spans"] == 0
    assert report["missing_chars"] == 0
    assert report["gaps"] == []
    assert report["punctuation_chars"] > 0
    assert report["content_coverage"] == 1.0
    assert report["coverage"] < 1.0


def test_alignment_reports_real_missing_content_and_coverage():
    report = alignment("甲乙丙丁戊", [{"text": "甲乙"}])

    assert report["missing_chars"] == 3
    assert report["missing_spans"] == 1
    assert report["content_coverage"] == pytest.approx(0.4)
    assert report["gaps"][0]["text"] == "丙丁戊"
    assert report["gaps"][0]["start"] == 2
    assert report["gaps"][0]["end"] == 5


def test_repair_tail_appends_missing_tail():
    original = "他说完了。然后他走了。"
    lines = [line("他说完了。")]
    before = len(lines)

    added = repair_tail(original, lines)

    assert added == len("然后他走了。")
    assert len(lines) == before + 1
    assert lines[-1].character == "旁白"
    assert lines[-1].text == "然后他走了。"
    assert lines[-1].emotion == "calm"


def test_repair_tail_is_noop_when_nothing_is_missing():
    original = "他说完了。"
    lines = [line("他说完了。")]

    assert repair_tail(original, lines) == 0
    assert [ln.text for ln in lines] == ["他说完了。"]


def test_repair_attributions_inserts_missing_speaker_line():
    # 原文引号之间是「朱先生问」，剧本把它整段吃掉了
    original = "你好。”朱先生问。“你是谁？"
    lines = [line("你好。"), line("你是谁？")]

    fixed = repair_attributions(original, lines)

    assert fixed == 1
    assert len(lines) == 3
    assert [ln.text for ln in lines] == ["你好。", "朱先生问", "你是谁？"]
    assert lines[1].character == "旁白"
    assert lines[1].emotion == "neutral"


def test_dedupe_keeps_short_exclamation_repeats():
    # 「住手！」连续两次是真台词，不能当重复删
    lines = [line("住手！", "叶秋"), line("住手！", "叶秋")]
    out, removed = dedupe_adjacent(lines)
    assert removed == 0
    assert [ln.text for ln in out] == ["住手！", "住手！"]

    # 长感叹句同样保留（走 endswith("！") 分支）
    shout = "你千万不要再这样继续下去了！"
    out, removed = dedupe_adjacent([line(shout, "叶秋"), line(shout, "叶秋")])
    assert removed == 0
    assert len(out) == 2


def test_dedupe_removes_identical_long_lines_only():
    sentence = "他推开门缓缓地走进了那间空荡荡的屋子。"
    out, removed = dedupe_adjacent([line(sentence), line(sentence), line("别人说话了。")])

    assert removed == 1
    assert [ln.text for ln in out] == [sentence, "别人说话了。"]

    # 同文不同角色不是重复
    out, removed = dedupe_adjacent([line(sentence, "叶修"), line(sentence, "苏沐橙")])
    assert removed == 0


def test_format_gap_truncates_long_text():
    gap = {"start": 12, "kind": "delete", "text": "很长的缺失" * 30}
    rendered = format_gap(gap)
    assert rendered.startswith("@12 [delete] …")
    assert rendered.endswith("…")
    assert len(rendered) < 100
