"""单元测试：全书角色表（novelcast.character_registry）。"""

from __future__ import annotations

import pytest

from novelcast.character_registry import (
    MAX_ALIASES,
    is_valid_name,
    merge_entries,
    names_from_prompt_map,
    roster_to_prompt_map,
    sort_roster,
)


def test_merge_entries_inserts_new_character():
    characters: dict = {}
    added = merge_entries(
        characters,
        [
            {
                "name": "叶修",
                "aliases": ["叶秋", "他", ""],
                "gender": "male",
                "age": "adult",
                "role": "protagonist",
                "description": "荣耀第一人",
            }
        ],
    )

    assert added == 1
    info = characters["叶修"]
    assert info["aliases"] == ["叶秋"]  # 代词/空别名被过滤
    assert info["appearances"] == 1
    assert info["gender"] == "male"
    assert info["age"] == "adult"
    assert info["role"] == "protagonist"
    assert info["description"] == "荣耀第一人"


def test_merge_entries_updates_existing_via_alias():
    characters: dict = {}
    merge_entries(
        characters,
        [{"name": "叶修", "aliases": ["叶秋"], "gender": "unknown", "role": "minor"}],
    )
    merge_entries(
        characters,
        [
            {
                "name": "叶秋",
                "aliases": ["一叶之秋", "叶修"],
                "gender": "male",
                "description": "比第一条更长的描述",
            }
        ],
    )

    assert list(characters) == ["叶修"]  # 通过别名归并，没有新增条目
    info = characters["叶修"]
    assert info["appearances"] == 2
    assert info["aliases"] == ["叶秋", "一叶之秋"]  # 别名取并集，不重复收录规范名
    assert info["gender"] == "male"  # 空字段被补全
    assert info["description"] == "比第一条更长的描述"  # 保留更长的描述


def test_merge_entries_caps_aliases_and_accumulates_appearances():
    characters: dict = {}
    aliases = [f"别名{i}" for i in range(MAX_ALIASES + 4)]
    merge_entries(characters, [{"name": "老王", "aliases": aliases, "appearances": 99}])

    assert len(characters["老王"]["aliases"]) == MAX_ALIASES
    # 条目自带的 appearances 不覆盖计数：以合并次数为准
    assert characters["老王"]["appearances"] == 1

    for _ in range(2):
        merge_entries(characters, [{"name": "老王", "appearances": 99}])
    assert characters["老王"]["appearances"] == 3


def test_merge_entries_filters_junk_names():
    characters: dict = {}
    added = merge_entries(
        characters,
        [
            {"name": "他"},
            {"name": "说道"},
            {"name": "调皮地"},
            {"name": "123"},
            {"name": "   "},
            {"name": "叶修"},
        ],
    )

    assert added == 1
    assert list(characters) == ["叶修"]


def test_sort_roster_orders_by_role_then_appearances_then_name():
    characters = {
        "路人甲": {"role": "minor", "appearances": 50},
        "配角": {"role": "supporting", "appearances": 3},
        "主角乙": {"role": "protagonist", "appearances": 2},
        "主角甲": {"role": "protagonist", "appearances": 9},
        "龙套乙": {"role": "minor", "appearances": 1},
        "龙套甲": {"role": "minor", "appearances": 1},
    }

    ordered = sort_roster(characters)

    assert list(ordered) == ["主角甲", "主角乙", "配角", "路人甲", "龙套乙", "龙套甲"]
    assert set(ordered) == set(characters)


def test_roster_to_prompt_map_format():
    roster = {
        "characters": {
            "叶修": {"aliases": ["叶秋", "一叶之秋"], "gender": "male", "age": "adult", "role": "protagonist"},
            "苏沐橙": {"aliases": [], "gender": "female", "age": "teen", "role": "supporting"},
            "老王": {"gender": "unknown", "age": "unknown", "role": "minor"},
        }
    }

    text = roster_to_prompt_map(roster)

    assert text.splitlines() == [
        "- 叶修（别名：叶秋、一叶之秋；男/成年；主角）",
        "- 苏沐橙（女/少年）",
        "- 老王",
    ]
    assert roster_to_prompt_map({}) == "（暂无已知角色）"


def test_roster_to_prompt_map_truncates_at_max_chars():
    roster = {"characters": {f"角色{i}": {"gender": "male"} for i in range(200)}}

    text = roster_to_prompt_map(roster, max_chars=50)

    assert text.splitlines()[-1] == "- …（其余角色略）"
    assert len("\n".join(text.splitlines()[:-1])) <= 50


def test_names_from_prompt_map_parsing():
    roster = {
        "characters": {
            "叶修": {"aliases": ["叶秋"], "gender": "male", "role": "protagonist"},
            "苏沐橙": {"aliases": [], "gender": "female"},
        }
    }
    assert names_from_prompt_map(roster_to_prompt_map(roster)) == ["叶修", "苏沐橙"]

    raw = "- 叶修（别名：叶秋）\n- 老王\n- …（其余角色略）\n这一行不是条目"
    assert names_from_prompt_map(raw) == ["叶修", "老王"]
    assert names_from_prompt_map("") == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("叶修", True),
        ("赵队长", True),
        ("母亲", True),
        ("他", False),
        ("我们", False),
        ("大家", False),
        ("说道", False),
        ("笑道", False),
        ("点头", False),
        ("调皮地", False),
        ("走了", False),
        ("来了", False),
        ("123", False),
        ("", False),
        ("一二三四五六七八九十一二三四五六七八九十一", False),  # 超过 20 字
    ],
)
def test_is_valid_name(name, expected):
    assert is_valid_name(name) is expected
