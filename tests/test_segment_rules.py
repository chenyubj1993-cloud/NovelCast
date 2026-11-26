"""单元测试：确定性剧本修复规则（novelcast.segment_rules）。"""

from __future__ import annotations

from novelcast.segment_rules import (
    UNKNOWN,
    count_bad_lines,
    postprocess_lines,
    split_line,
)


def narrate(text: str, character: str = "旁白") -> dict:
    return {"character": character, "text": text, "emotion": "neutral"}


def fix(text: str, names: list[str]):
    out, stats = postprocess_lines([narrate(text)], names)
    return [(item["character"], item["text"]) for item in out], stats


def test_narration_with_paired_quotes_splits_into_narration_and_dialogue():
    pieces, stats = fix("他推门而入，叶秋说道：“来了。”众人回头。", ["叶秋"])

    assert pieces == [
        ("旁白", "他推门而入，叶秋说道："),
        ("叶秋", "来了。"),
        ("旁白", "众人回头。"),
    ]
    assert stats["split"] == 1
    assert stats["unknown"] == 0
    assert stats["kept"] == 3


def test_speaker_inferred_from_name_and_speech_verb_with_colon():
    pieces, _ = fix("苏沐橙说道：“你好呀。”", ["苏沐橙"])
    assert pieces == [("旁白", "苏沐橙说道："), ("苏沐橙", "你好呀。")]

    # 半角冒号同样要能取到说话人
    pieces, _ = fix('苏沐橙说道: "你好呀。"', ["苏沐橙"])
    assert pieces == [("旁白", "苏沐橙说道:"), ("苏沐橙", "你好呀。")]


def test_speaker_inferred_from_adverbial_between_name_and_verb():
    # 「看着他道：」是状语插在名字和动词之间，冒号必须能被规则接受
    pieces, _ = fix("叶秋看着他道：“来了。”", ["叶秋"])
    assert pieces == [("旁白", "叶秋看着他道："), ("叶秋", "来了。")]


def test_unknown_when_no_name_can_be_inferred():
    pieces, stats = fix("“来了。”", [])

    assert pieces == [(UNKNOWN, "来了。")]
    assert stats["unknown"] == 1
    assert stats["split"] == 0  # 只切出一段，不算“拆分”

    # 名字是动词宾语时也不能当说话人：应落到「未知」而不是旁白
    pieces, _ = fix("她瞅到了犹豫的叶秋，气冲冲地问道：“上机啊？”", ["叶秋"])
    assert pieces[-1][0] == UNKNOWN


def test_full_quote_line_of_known_character_is_kept_as_is():
    pieces = split_line("叶秋", "“来了。”", "neutral", ["叶秋"])
    assert pieces == [("叶秋", "“来了。”", "neutral")]


def test_non_narration_lines_are_not_split():
    out, stats = postprocess_lines(
        [narrate("叶秋说道：“来了。”", character="叶秋")],
        ["叶秋"],
    )

    assert [(item["character"], item["text"]) for item in out] == [("叶秋", "叶秋说道：“来了。”")]
    assert stats["split"] == 0


def test_count_bad_lines_counts_narration_containing_quotes():
    lines = [
        {"character": "旁白", "text": "他说道：“来了。”"},
        {"character": "叶秋", "text": "“来了。”"},
        {"character": "旁白", "text": "没有引号的一句。"},
    ]
    assert count_bad_lines(lines) == 1


def test_empty_text_lines_are_dropped():
    out, stats = postprocess_lines(
        [narrate("   "), narrate("有内容。")],
        [],
    )
    assert [(item["character"], item["text"]) for item in out] == [("旁白", "有内容。")]
    assert stats["kept"] == 1
