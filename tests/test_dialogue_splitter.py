"""unit tests for novelcast.dialogue_splitter helpers (no network)."""

from __future__ import annotations

from novelcast.dialogue_splitter import (
    DialogueLine,
    RateLimiter,
    _fallback_split,
    _parse_llm_response,
    _split_fixed_segments,
    _split_text_chunks,
    _verify_coverage,
    is_valid_character_name,
    sanitize_character_name,
)


def test_parse_json_array_with_fence():
    raw = '好的，结果如下：\n```json\n[{"character":"叶秋","text":"来了。","emotion":"neutral"}]\n```'
    lines = _parse_llm_response(raw, "来了。")
    assert isinstance(lines, list) and lines
    assert isinstance(lines[0], DialogueLine)
    assert lines[0].text == "来了。"


def test_parse_plain_array():
    raw = '[{"character":"旁白","text":"夜色渐深。","emotion":"neutral"}]'
    lines = _parse_llm_response(raw, "夜色渐深。")
    assert lines[0].character == "旁白"


def test_parse_garbage_falls_back_without_losing_text():
    original = "他推门进来，看了我一眼。"
    lines = _parse_llm_response("模型今天不想输出 JSON", original)
    joined = "".join(line.text for line in lines)
    assert joined.strip()
    assert "推门" in joined


def test_fallback_covers_text():
    text = "第一段。\n\n第二段。\n\n第三段。"
    lines = _fallback_split(text)
    assert "".join(l.text for l in lines).replace("\n", "") == text.replace("\n", "")


def test_verify_coverage_ratio():
    text = "一二三四五六七八九十"
    full = [DialogueLine(character="旁白", text=text, emotion="neutral")]
    none = [DialogueLine(character="旁白", text="一二三", emotion="neutral")]
    assert _verify_coverage(text, full) == 1.0
    assert 0.2 < _verify_coverage(text, none) < 0.4


def test_split_text_chunks_reassembles():
    text = ("句子。" * 100 + "\n\n") * 5
    chunks = _split_text_chunks(text, 1500)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_split_fixed_segments_are_lossless():
    text = "甲乙丙丁。戊己庚辛。壬癸。"
    segs = _split_fixed_segments(text, 3)
    assert len(segs) <= 3
    assert "".join(segs) == text


def test_sanitize_junk_names():
    assert sanitize_character_name("他") == "旁白"
    assert sanitize_character_name("") == "旁白"
    assert sanitize_character_name("叶秋") == "叶秋"
    assert is_valid_character_name("叶秋")
    assert not is_valid_character_name("他")


def test_rate_limiter_accepts():
    import asyncio

    async def run():
        limiter = RateLimiter(6000)
        for _ in range(3):
            await limiter.acquire()

    asyncio.run(run())
