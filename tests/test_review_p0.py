"""回归测试：2026-11 review 的 P0 问题（归属冒号、BOM、模板页、角色名解析、edge 音色）。"""
import pytest

from novelcast.character_registry import names_from_prompt_map, roster_to_prompt_map
from novelcast.novel_reader import split_chapters
from novelcast.segment_rules import postprocess_lines
from novelcast.tts_providers import EdgeTTSProvider


def _fix(text, names):
    out, _stats = postprocess_lines(
        [{"character": "旁白", "text": text, "emotion": ""}], names
    )
    return [(o["character"], o["text"]) for o in out]


def test_attribution_with_fullwidth_colon():
    assert _fix("叶秋说道：“来了。”", ["叶秋"]) == [
        ("旁白", "叶秋说道："),
        ("叶秋", "来了。"),
    ]


def test_attribution_with_adverbial_between_name_and_verb():
    assert _fix("叶秋看着他道：“来了。”", ["叶秋"]) == [
        ("旁白", "叶秋看着他道："),
        ("叶秋", "来了。"),
    ]


def test_attribution_still_rejects_object_before_verb():
    # 「瞅到了犹豫的叶秋，气冲冲地问道」里的叶秋是宾语，不能当说话人
    result = _fix("她瞅到了犹豫的叶秋，气冲冲地问道：“上机啊？”", ["叶秋"])
    assert result[-1][0] in ("未知", "")


def test_bom_does_not_break_chapter_split():
    chapters = split_chapters("\ufeff第一章 开始\n正文一。\n第二章 继续\n正文二。")
    assert [c.title for c in chapters] == ["第一章 开始", "第二章 继续"]


def test_template_page_dropped():
    text = "第一章 开始\n正文一。\n警告：这个文件不要做任何改动\n书名在title.xhtml中填写\n第二章 继续\n正文二。"
    chapters = split_chapters(text)
    assert [c.title for c in chapters] == ["第一章 开始", "第二章 继续"]
    assert "title.xhtml" not in chapters[0].text
    assert "正文一。" in chapters[0].text


def test_names_from_prompt_map():
    roster = {
        "characters": {
            "叶修": {"gender": "male", "age": "young", "role": "protagonist"},
            "陈果": {"gender": "female", "age": "young", "role": "supporting"},
        }
    }
    assert names_from_prompt_map(roster_to_prompt_map(roster)) == ["叶修", "陈果"]


def test_edge_voice_name_resolves_to_azure_id():
    assert EdgeTTSProvider().resolve_voice("白桦") == "zh-CN-YunyangNeural"
    assert EdgeTTSProvider().resolve_voice("zh-CN-XiaoxiaoNeural") == "zh-CN-XiaoxiaoNeural"


def test_cli_rejects_mimoai():
    from novelcast.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "x.txt", "--tts", "mimoai"])


def test_cli_rejects_fresh_with_offline():
    from novelcast.cli import main

    assert main(["run", "input/全职高手.epub", "--fresh", "--offline"]) == 2


def test_safe_filename():
    from novelcast.utils import safe_filename

    assert safe_filename("第1章 他/她: 说?") == "第1章 他_她_ 说_"
    assert safe_filename("...") == "untitled"


def test_numeric_body_line_not_chapter():
    chapters = split_chapters("1. 他走了。\n正文。\n2. 她也走了。\n更多正文。")
    assert len(chapters) == 1


def test_edge_branch_passes_voice_name_not_file_path(tmp_path):
    import numpy as np
    import soundfile as sf

    from novelcast.local_tts import synthesize_lines

    class FakeEdge:
        name = "edge"
        kind = "local"
        version = ""
        model_dir = ""
        duration_factor = 0.9
        lang = "zh"
        emotion_mode = "text"
        emo_alpha = 0.55
        rate = "+11%"

        def __init__(self):
            self.refs = []

        def synthesize(self, text, ref, out, emotion=None):
            self.refs.append(ref)
            sf.write(out, np.zeros(2400, dtype="float32"), 24000, format="WAV")

    provider = FakeEdge()
    lines = [{"text": "来了。", "character": "叶秋", "emotion": "", "voice_id": "白桦"}]
    synthesize_lines(
        lines,
        str(tmp_path / "work"),
        refs_dir=str(tmp_path / "refs"),
        provider=provider,
        verbose=False,
        restart=True,
    )
    assert provider.refs == ["白桦"]
