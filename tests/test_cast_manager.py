"""单元测试：全书音色分配（novelcast.cast_manager）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from novelcast.cast_manager import (
    GENDER_VOICES,
    _is_crowd,
    _stable_index,
    apply_cast,
    build_cast,
    load_cast,
    load_voice_bank,
    save_cast,
)

EDGE_FEMALE = set(GENDER_VOICES["female"])
EDGE_MALE = set(GENDER_VOICES["male"])

BANK_VOICES = [
    {"id": "播音男一", "gender": "male", "style": "broadcast"},
    {"id": "播音男二", "gender": "male", "style": "broadcast"},
    {"id": "播音女一", "gender": "female", "style": "broadcast"},
    {"id": "朗读男一", "gender": "male", "style": "read"},
    {"id": "朗读女一", "gender": "female", "style": "read"},
]


class FakeLine:
    def __init__(self, character: str, text: str = "", emotion: str = "neutral"):
        self.character = character
        self.text = text
        self.emotion = emotion
        self.voice_id = ""


def make_config(**overrides) -> SimpleNamespace:
    cfg = {
        "voice_presets": {"default": "冰糖", "main_male": "白桦", "main_female": "冰糖", "extra": "云希"},
        "main_character_count": 1,
    }
    cfg.update(overrides)
    return SimpleNamespace(config=cfg)


def write_bank(tmp_path, voices):
    path = tmp_path / "voice_bank.json"
    path.write_text(json.dumps({"voices": voices}, ensure_ascii=False), encoding="utf-8")
    return path


def roster_entry(name: str, gender: str, role: str, appearances: int, aliases=None) -> dict:
    return {
        "name": name,
        "aliases": list(aliases or []),
        "gender": gender,
        "age": "adult",
        "role": role,
        "appearances": appearances,
    }


def test_build_cast_main_uses_edge_presets_minor_uses_voice_bank(tmp_path):
    bank_path = write_bank(tmp_path, BANK_VOICES)
    roster = {
        "characters": {
            "叶修": roster_entry("叶修", "male", "protagonist", 100),
            "女配": roster_entry("女配", "female", "supporting", 5),
            "小配角": roster_entry("小配角", "male", "minor", 1),
        }
    }

    cast = build_cast(roster, make_config(voice_bank=str(bank_path)))

    assert cast["narrator"] == "冰糖"
    # 主角色沿用内置 edge 预设
    assert cast["voices"]["叶修"] == "白桦"
    assert cast["voices"]["叶修"] in EDGE_MALE
    # 次要角色用音色库里的「播音」真人音色，且不占用 edge 预设名
    assert cast["voices"]["小配角"] == "播音男一"
    assert cast["voices"]["小配角"] not in EDGE_MALE | EDGE_FEMALE
    assert cast["voices"]["女配"] == "播音女一"
    assert cast["voice_bank"] == str(bank_path)
    assert "白桦" not in cast["crowd_pool"]


def test_build_cast_alias_shares_the_same_voice(tmp_path):
    roster = {
        "characters": {
            "叶修": roster_entry("叶修", "male", "protagonist", 10, aliases=["叶秋", "一叶之秋"]),
        }
    }

    cast = build_cast(roster, make_config(voice_bank=str(tmp_path / "不存在的音色库.json")))

    assert cast["voices"]["叶秋"] == cast["voices"]["叶修"]
    assert cast["voices"]["一叶之秋"] == cast["voices"]["叶修"]


def test_build_cast_voice_bank_fallback_when_missing_or_broken(tmp_path):
    assert load_voice_bank(tmp_path / "nope.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    assert load_voice_bank(broken) is None

    empty = tmp_path / "empty.json"
    empty.write_text('{"voices": []}', encoding="utf-8")
    assert load_voice_bank(empty) is None

    # 音色库缺失时回退到内置 edge 预设，且次要角色也会分到不同的预设音色
    roster = {
        "characters": {
            "叶修": roster_entry("叶修", "male", "protagonist", 10),
            "小配角": roster_entry("小配角", "male", "minor", 1),
        }
    }
    cast = build_cast(roster, make_config(voice_bank=str(tmp_path / "nope.json")))

    assert cast["voice_bank"] == ""
    for name in ("叶修", "小配角"):
        assert cast["voices"][name] in EDGE_MALE | EDGE_FEMALE
    assert cast["voices"]["小配角"] != cast["voices"]["叶修"]


def test_build_cast_extra_characters_merge_and_max_appearances(tmp_path):
    roster = {"characters": {"叶修": roster_entry("叶修", "male", "protagonist", 2)}}

    cast = build_cast(
        roster,
        make_config(voice_bank=str(tmp_path / "nope.json")),
        extra_characters={"叶修": 9, "龙套甲": 3},
    )

    assert cast["characters"]["叶修"]["appearances"] == 9  # max(旧, 新)
    extra = cast["characters"]["龙套甲"]
    assert extra["appearances"] == 3
    assert extra["role"] == "minor"
    assert extra["gender"] == "unknown"
    assert "龙套甲" in cast["voices"]


def test_apply_cast_crowd_rotation_alternates_genders():
    cast = {
        "narrator": "旁白音",
        "voices": {},
        "crowd_pool": ["女一", "男一", "女二", "男二"],
        "crowd_genders": {"女一": "female", "男一": "male", "女二": "female", "男二": "male"},
    }
    lines = [FakeLine("众人"), FakeLine("路人"), FakeLine("众人"), FakeLine("群众")]

    unknown = apply_cast(lines, cast)

    assert unknown == []
    assert [ln.voice_id for ln in lines] == ["女一", "男一", "女二", "男二"]


def test_apply_cast_crowd_skips_previous_voice_on_repeat():
    # 音色池里有重复项时，轮换不能连续两次发出同一个声音
    cast = {
        "narrator": "旁白音",
        "voices": {},
        "crowd_pool": ["女一", "男一", "女一"],
        "crowd_genders": {"女一": "female", "男一": "male"},
    }
    lines = [FakeLine("众人") for _ in range(4)]

    apply_cast(lines, cast)

    assert [ln.voice_id for ln in lines] == ["女一", "男一", "女一", "男一"]


def test_apply_cast_out_of_roster_gets_stable_voice_from_crowd_pool():
    pool = ["群一", "群二", "群三"]
    cast = {"narrator": "旁白音", "voices": {"叶修": "白桦"}, "crowd_pool": pool, "crowd_genders": {}}

    first = FakeLine("张秀才")
    unknown = apply_cast([first], cast)

    assert unknown == ["张秀才"]
    assert first.voice_id == pool[_stable_index("张秀才", len(pool))]

    second = FakeLine("张秀才")
    apply_cast([second], cast)
    assert second.voice_id == first.voice_id


def test_apply_cast_known_character_and_narrator_fallback():
    cast = {"narrator": "旁白音", "voices": {"叶修": "白桦"}}

    known = FakeLine("叶修")
    stranger = FakeLine("张秀才")
    unknown = apply_cast([known, stranger], cast)

    assert known.voice_id == "白桦"
    assert stranger.voice_id == "旁白音"  # 没有群杂池时回退旁白
    assert unknown == ["张秀才"]

    # 关闭回退：仍报告未知角色，但音色留空
    muted = FakeLine("张秀才")
    assert apply_cast([muted], cast, narrator_fallback=False) == ["张秀才"]
    assert muted.voice_id == ""


def test_is_crowd_recognizes_group_names():
    assert _is_crowd("众人") is True
    assert _is_crowd("围观群众甲") is True
    assert _is_crowd("群杂") is True
    assert _is_crowd("叶修") is False
    assert _is_crowd("") is False


def test_save_load_roundtrip(tmp_path):
    cast = {
        "version": 1,
        "narrator": "冰糖",
        "voices": {"旁白": "冰糖", "叶修": "白桦"},
        "crowd_pool": ["群一", "群二"],
    }
    path = tmp_path / "cast" / "cast.json"

    save_cast(cast, path)

    assert load_cast(path) == cast
    assert [p.name for p in path.parent.iterdir()] == ["cast.json"]  # 临时文件已替换
    assert load_cast(tmp_path / "missing.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    assert load_cast(broken) is None

    no_voices = tmp_path / "no_voices.json"
    no_voices.write_text('{"version": 1}', encoding="utf-8")
    assert load_cast(no_voices) is None
