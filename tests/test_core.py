# -*- coding: utf-8 -*-
"""离线单元测试：不依赖 LLM / TTS API，覆盖角色表、音色表、缓存。"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_test"


def tmpdir(name):
    """用工作区内目录做临时目录（系统 %TEMP% 可能被沙箱限制）。"""
    path = TMP_ROOT / name
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path

from novelcast.cast_manager import apply_cast, build_cast, load_cast, save_cast
from novelcast.character_registry import (
    is_valid_name,
    merge_entries,
    roster_to_prompt_map,
    sort_roster,
)
from novelcast.llm_cache import LlmCache
from novelcast.local_tts import split_text_for_tts


class Cfg:
    def __init__(self, config):
        self.config = config


def base_config():
    return {
        "voice_presets": {
            "冰糖": "冰糖", "苏打": "苏打", "茉莉": "茉莉", "白桦": "白桦",
            "Mia": "Mia", "Chloe": "Chloe", "Milo": "Milo", "Dean": "Dean",
            "default": "冰糖",
        },
        "character_voices": {"旁白": "冰糖"},
        # 测试不读真实的 output/_refs/voice_bank.json，保built-in 音色行为可预期
        "voice_bank": str(TMP_ROOT / "no_bank.json"),
    }


def test_merge_and_alias():
    chars = {}
    merge_entries(chars, [{
        "name": "林黛玉", "aliases": ["黛玉"], "gender": "female",
        "age": "teen", "role": "protagonist", "description": "绛珠仙草转世",
    }])
    merge_entries(chars, [{
        "name": "黛玉", "aliases": ["林妹妹"], "gender": "female",
        "age": "teen", "role": "protagonist", "description": "",
    }])
    assert list(chars) == ["林黛玉"], chars
    assert "林妹妹" in chars["林黛玉"]["aliases"]
    assert chars["林黛玉"]["appearances"] == 2


def test_junk_filtered():
    chars = {}
    merge_entries(chars, [
        {"name": "他"}, {"name": "说"}, {"name": "众人"},
        {"name": "贾宝玉", "aliases": []},
    ])
    assert list(chars) == ["贾宝玉"]
    assert not is_valid_name("他们")


def test_prompt_map():
    roster = {"characters": sort_roster({
        "林黛玉": {"name": "林黛玉", "aliases": ["黛玉"], "gender": "female",
                 "age": "teen", "role": "protagonist", "appearances": 9},
        "贾宝玉": {"name": "贾宝玉", "aliases": [], "gender": "male",
                 "age": "teen", "role": "protagonist", "appearances": 8},
    })}
    text = roster_to_prompt_map(roster)
    assert "林黛玉" in text and "黛玉" in text and "女" in text
    assert text.index("林黛玉") < text.index("贾宝玉")


def test_cast_unique_voices():
    roster = {"characters": {
        "林黛玉": {"gender": "female", "age": "teen", "role": "protagonist", "appearances": 9},
        "贾宝玉": {"gender": "male", "age": "teen", "role": "protagonist", "appearances": 8},
        "薛宝钗": {"gender": "female", "age": "teen", "role": "supporting", "appearances": 5},
    }}
    cast = build_cast(roster, Cfg(base_config()))
    voices = cast["voices"]
    assert voices["旁白"] == "冰糖"
    assert voices["林黛玉"] != voices["薛宝钗"], "同性别角色不应撞音"
    assert voices["贾宝玉"] in {"白桦", "Milo", "Dean"}
    assert "冰糖" not in (voices["林黛玉"],), "旁白音色应保留"


def test_cast_override_and_extras():
    cfg = base_config()
    cfg["character_voices"]["宝玉"] = "Milo"
    roster = {"characters": {"贾宝玉": {"aliases": ["宝玉"], "gender": "male",
                                        "age": "teen", "role": "protagonist", "appearances": 3}}}
    cast = build_cast(roster, Cfg(cfg), extra_characters={"茗烟": 2})
    assert cast["voices"]["贾宝玉"] == "Milo"
    assert "茗烟" in cast["voices"]


def test_apply_cast_unknown():
    class Line:
        def __init__(self, character):
            self.character = character
            self.voice_id = ""

    cast = {"narrator": "冰糖", "voices": {"旁白": "冰糖", "林黛玉": "茉莉"}}
    lines = [Line("旁白"), Line("林黛玉"), Line("陌生人")]
    unknown = apply_cast(lines, cast)
    assert [l.voice_id for l in lines] == ["冰糖", "茉莉", "冰糖"]
    assert unknown == ["陌生人"]


def test_cast_roundtrip():
    cast = {"version": 1, "narrator": "冰糖", "voices": {"旁白": "冰糖"}}
    path = tmpdir("cast") / "cast.json"
    save_cast(cast, path)
    assert load_cast(path)["voices"]["旁白"] == "冰糖"


def test_llm_cache():
    cache = LlmCache("测试书", "model-x", "prompt-v1", root=tmpdir("cache"))
    assert cache.get("第一段", context="{}") is None
    cache.put("第一段", [{"character": "旁白", "text": "第一段", "emotion": "neutral"}], context="{}")
    hit = cache.get("第一段", context="{}")
    assert hit and hit[0]["text"] == "第一段"
    assert cache.get("第一段", context='{"a": 1}') is None, "角色表不同不应命中"
    assert cache.stats["hits"] == 1


def test_split_long_line_lossless():
    text = "这是一段没有标点的超长旁白" * 12
    parts = split_text_for_tts(text)
    assert len(parts) > 1
    assert max(len(p) for p in parts) <= 80
    assert "".join(parts) == text


def test_split_short_line_kept():
    text = "“上机啊？”"
    assert split_text_for_tts(text) == [text]


def test_crowd_rotation():
    from types import SimpleNamespace

    cast = {"narrator": "N", "voices": {"旁白": "N", "众人": "C1", "甲": "A", "乙": "B"}}
    lines = [SimpleNamespace(character="众人") for _ in range(3)]
    apply_cast(lines, cast)
    assert len({l.voice_id for l in lines}) == 3, "三条众人应有三种声音"
    assert all(l.voice_id != "N" for l in lines), "群杂不应使用旁白音色"


def test_cast_from_voice_bank():
    import json

    d = tmpdir("bank")
    bank = {
        "version": 1,
        "voices": [
            {"id": "A3-F1", "gender": "female"},
            {"id": "A3-F2", "gender": "female"},
            {"id": "A3-M1", "gender": "male"},
        ],
    }
    (d / "voice_bank.json").write_text(json.dumps(bank), encoding="utf-8")

    cfg = base_config()
    cfg["voice_bank"] = str(d / "voice_bank.json")
    cfg["main_character_count"] = 1
    roster = {
        "characters": {
            "甲": {"name": "甲", "gender": "male", "role": "lead", "appearances": 50},
            "乙": {"name": "乙", "gender": "female", "role": "minor", "appearances": 3},
            "丙": {"name": "丙", "gender": "female", "role": "minor", "appearances": 1},
        }
    }
    cast = build_cast(roster, Cfg(cfg))
    # 主角沿用原来的 edge 音色，次要角色才用真人音色库
    assert cast["voices"]["甲"] in {"白桦", "Milo", "Dean"}
    assert cast["voices"]["乙"] == "A3-F1"
    assert cast["voices"]["丙"] == "A3-F2"
    assert cast["narrator"] == "冰糖"
    assert cast["voice_bank"].endswith("voice_bank.json")


def test_cast_falls_back_without_bank():
    cfg = base_config()
    cfg["voice_bank"] = str(tmpdir("nobank") / "missing.json")
    cast = build_cast({"characters": {"甲": {"name": "甲", "gender": "male"}}}, Cfg(cfg))
    assert cast["voices"]["甲"] in {"白桦", "Milo", "Dean"}


def test_main_uses_original_voices():
    import json

    d = tmpdir("mainbank")
    bank = {"version": 1, "voices": [
        {"id": "A3-F1", "gender": "female"},
        {"id": "A3-M1", "gender": "male"},
    ]}
    (d / "voice_bank.json").write_text(json.dumps(bank), encoding="utf-8")
    cfg = base_config()
    cfg["voice_bank"] = str(d / "voice_bank.json")
    cfg["main_character_count"] = 1
    roster = {"characters": {
        "甲": {"name": "甲", "gender": "male", "appearances": 50},
        "乙": {"name": "乙", "gender": "female", "appearances": 2},
    }}
    cast = build_cast(roster, Cfg(cfg))
    assert cast["narrator"] == "冰糖"
    assert cast["voices"]["甲"] in {"白桦", "Milo", "Dean", "苏打"}, cast["voices"]
    assert cast["voices"]["乙"] == "A3-F1", cast["voices"]


def test_crowd_gender_alternates():
    from types import SimpleNamespace

    cast = {
        "narrator": "N", "voices": {"旁白": "N", "众人": "C"},
        "crowd_pool": ["F1", "M1"],
        "crowd_genders": {"F1": "female", "M1": "male"},
    }
    lines = [SimpleNamespace(character="众人") for _ in range(4)]
    apply_cast(lines, cast)
    assert [l.voice_id for l in lines] == ["F1", "M1", "F1", "M1"]


def test_repair_attribution():
    from novelcast.dialogue_splitter import DialogueLine
    from novelcast.script_qa import alignment, repair_attributions

    original = "“走。”朱先生问：“去哪？”"
    lines = [
        DialogueLine(character="旁白", text="走。", emotion="calm", voice_id=""),
        DialogueLine(character="白孝文", text="去哪？", emotion="calm", voice_id=""),
    ]
    assert alignment(original, lines)["missing_chars"] >= 4
    assert repair_attributions(original, lines) >= 1
    assert any(l.character == "旁白" and "朱先生" in l.text for l in lines)


def test_script_alignment_ignores_quotes():
    from novelcast.dialogue_splitter import DialogueLine
    from novelcast.script_qa import alignment

    original = "他说：“走吧。”"
    lines = [DialogueLine(character="旁白", text="他说：", emotion="calm", voice_id=""),
             DialogueLine(character="某人", text="走吧。", emotion="calm", voice_id="")]
    report = alignment(original, lines)
    assert report["missing_chars"] == 0, report
    assert report["punctuation_chars"] >= 2


def test_script_alignment_detects_and_repairs_tail():
    from novelcast.dialogue_splitter import DialogueLine
    from novelcast.script_qa import alignment, repair_tail

    original = "甲乙丙丁戊己庚辛"
    lines = [DialogueLine(character="旁白", text="甲乙丙丁", emotion="calm", voice_id="")]
    report = alignment(original, lines)
    assert report["missing_chars"] == 4, report
    assert repair_tail(original, lines) == 4
    assert lines[-1].text == "戊己庚辛"
    assert alignment(original, lines)["coverage"] == 1.0


def test_pseudo_chapter_merged():
    from novelcast.novel_reader import split_chapters

    body = "正文" * 120
    text = f"封面\n版权\n\n第一章 开始\n{body}\n第二章 继续\n{body}"
    chapters = split_chapters(text)
    assert chapters[0].title == "第一章 开始", chapters[0].title
    assert "封面" in chapters[0].text
    assert [c.number for c in chapters] == list(range(1, len(chapters) + 1))


def test_out_of_roster_gets_stable_pool_voice():
    from types import SimpleNamespace

    from novelcast.cast_manager import apply_cast

    cast = {
        "narrator": "N",
        "voices": {"旁白": "N"},
        "crowd_pool": ["A", "B", "C"],
        "crowd_genders": {},
    }
    lines = [SimpleNamespace(character="张秀才") for _ in range(2)]
    apply_cast(lines, cast)
    assert lines[0].voice_id == lines[1].voice_id
    assert lines[0].voice_id in ("A", "B", "C")


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
