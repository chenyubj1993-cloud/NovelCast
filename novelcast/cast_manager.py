"""
全局音色分配（cast.json）

音色分配必须是"全书一次"的，而不是逐章各分各的：否则第 3 章的小明
是冰糖、第 7 章的小明就变成茉莉了。这里以角色表为准，按性别/年龄
挑音色、尽量不撞音，并把结果持久化，后续章节直接复用。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from novelcast.log import log

CAST_VERSION = 1

# 只用职务称呼、又没有独立角色条目的男性角色（「经理」「老板」这类）
MALE_TITLES = {"经理", "老板", "队长", "教练", "主任", "裁判", "主持人", "会长", "主席"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BANK_PATH = PROJECT_ROOT / "output" / "_refs" / "voice_bank.json"

# 音色性别倾向（可按自己的音色库调整）
GENDER_VOICES = {    # 只放「互不重复」的音色名：冰糖=Xiaoxiao、茉莉=Xiaoyi、Mia=Xiaochen、Chloe=Xiaohan、
    # 苏打=Xiaomeng、晓萱=Xiaoxuan、小北=Xiaobei(辽宁)、小妮=Xiaoni(陕西)
    "female": ["冰糖", "茉莉", "Mia", "Chloe", "苏打", "晓萱", "小北", "小妮"],
    # 白桦=Yunyang、Milo=Yunye、Dean=Yunjian、云希=Yunxi、云夏=Yunxia
    "male": ["白桦", "Milo", "Dean", "云希", "云夏"],
    "unknown": ["苏打"],
}


def load_voice_bank(path=None) -> Optional[dict]:
    """读取 voice_bank.json；没有就返回 None（回退到内置 8 音色）。"""
    bank_path = Path(path) if path else DEFAULT_BANK_PATH
    if not bank_path.exists():
        return None
    try:
        data = json.loads(bank_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or not data.get("voices"):
        return None
    data["_path"] = str(bank_path)
    data["_dir"] = str(bank_path.parent)
    return data


def _bank_pools(bank: dict) -> Dict[str, List[str]]:
    pools: Dict[str, List[str]] = {}
    for v in bank.get("voices", []):
        vid = v.get("id") or v.get("name")
        if not vid:
            continue
        pools.setdefault(v.get("gender", "unknown"), []).append(vid)
    return pools


def _resolve_override(name: str, info: dict, overrides: Dict[str, str], presets: Dict[str, str]) -> Optional[str]:
    """在 character_voices 配置里按规范名或别名找用户指定音色。"""
    candidates = [name] + list(info.get("aliases", []) or [])
    for candidate in candidates:
        if candidate in overrides:
            voice = overrides[candidate]
            return presets.get(voice, voice)
    return None


def build_cast(
    roster: Optional[dict],
    config,
    extra_characters: Optional[Dict[str, int]] = None,
) -> dict:
    """生成全书音色表。

    Args:
        roster: characters.json 的内容，可为空
        config: ConfigManager
        extra_characters: 阶段1 标注过程中新出现、角色表里没有的角色 -> 出现次数
    """
    voice_presets = config.config.get("voice_presets", {}) or {}
    default_voice = voice_presets.get("default", "冰糖")
    preset_names = [v for k, v in voice_presets.items() if k != "default"]
    preset_names = list(dict.fromkeys(preset_names)) or [default_voice]

    bank = load_voice_bank(config.config.get("voice_bank") or None)
    bank_pools = _bank_pools(bank) if bank else {}
    bank_all = [v for ids in bank_pools.values() for v in ids]
    # 音色库里的风格标记：broadcast（播音/新闻）、read（朗读）、storytelling（评书）
    bank_styles = {v.get("id"): v.get("style", "read") for v in (bank or {}).get("voices", [])}

    def _style_of(ids, style):
        return [v for v in ids if bank_styles.get(v) == style]

    # 留一批「朗读」音色专门给群杂轮换，避免全书角色把库用光后
    # 路人只能复用主角的声音。
    read_ids = _style_of(bank_all, "read")
    if len(read_ids) >= 24:
        gender_of = {v: g for g, ids in bank_pools.items() for v in ids}
        read_f = [v for v in read_ids if gender_of.get(v) == "female"]
        read_m = [v for v in read_ids if gender_of.get(v) == "male"]
        reserved_for_crowd = set(read_f[:8] + read_m[:8])
    else:
        reserved_for_crowd = set()

    overrides = config.config.get("character_voices", {}) or {}
    # 旁白沿用原来的 edge 音色（朗读更稳），除非 character_voices 显式指定
    narrator = overrides.get("旁白") or default_voice

    characters: Dict[str, dict] = {}
    for name, info in ((roster or {}).get("characters", {}) or {}).items():
        characters[name] = dict(info)
    for name, count in (extra_characters or {}).items():
        if name in characters:
            characters[name]["appearances"] = max(int(characters[name].get("appearances", 1)), count)
        else:
            characters[name] = {
                "name": name,
                "aliases": [],
                "gender": "unknown",
                "age": "unknown",
                "role": "minor",
                "description": "标注阶段出现、角色表未收录",
                "appearances": count,
            }

    from .character_registry import sort_roster

    characters = sort_roster(characters)

    tts_cfg = config.config.get("tts", {}) or {}
    if str(tts_cfg.get("provider", "")).lower() in ("openai", "cloud"):
        return _cloud_cast(characters, config, tts_cfg)

    # 主要角色：出场次数最多的前 N 个（也可以用 main_characters 显式指定），
    # 沿用原来的 8 个 edge 音色；次要角色和群杂才用真人音色库。
    main_names = config.config.get("main_characters") or []
    if not main_names:
        ranked = [n for n in characters if n != "旁白" and not _is_crowd(n)]
        ranked.sort(key=lambda n: int(characters[n].get("appearances", 1)), reverse=True)
        top_n = int(config.config.get("main_character_count", 6) or 6)
        main_names = ranked[:max(0, top_n)]
    main_set = set(main_names)

    voices: Dict[str, str] = {"旁白": narrator}
    used = {narrator}
    usage: Counter = Counter({narrator: 1})

    for name, info in characters.items():
        if name == "旁白":
            continue
        voice = _resolve_override(name, info, overrides, voice_presets)
        if voice:
            voices[name] = voice
            used.add(voice)
            usage[voice] += 1
            continue

        gender = info.get("gender", "unknown")
        if gender in ("", "unknown"):
            override = (config.config.get("character_genders") or {}).get(name)
            if override:
                gender = override
            elif name in MALE_TITLES:
                gender = "male"
        use_original = name in main_set or not bank_all
        if use_original:
            preferred = [v for v in GENDER_VOICES.get(gender, []) if v in preset_names]
            # 预设里没有的 edge 音色（云希/云扬…）排在后面，主角色多时补位，避免撞音
            preferred += [v for v in GENDER_VOICES.get(gender, []) if v not in preset_names]
            fallback = preferred or [v for v in preset_names if v not in (narrator,)]
            pool = [v for v in fallback if v not in used] or fallback
        else:
            # 次要角色优先用「播音腔」真人音色，和主角的 edge 播音腔更接近；
            # 不够时再退回普通朗读库。
            pool = [v for v in _style_of(bank_pools.get(gender, []), "broadcast") if v not in used]
            if not pool:
                pool = [v for v in bank_pools.get(gender, []) if v not in used and v not in reserved_for_crowd]
            if not pool:
                pool = [v for v in _style_of(bank_all, "broadcast") if v not in used]
            if not pool:
                pool = [v for v in bank_all if v not in reserved_for_crowd]
            if not pool:
                pool = list(bank_all)
        if not pool:
            pool = [default_voice]

        # 优先未使用；都用过了就让使用次数最少的顶上
        free = [v for v in pool if v not in used]
        voice = free[0] if free else min(pool, key=lambda v: usage[v])
        voices[name] = voice
        used.add(voice)
        usage[voice] += 1

    # 群杂专用池：用音色库里还没被主要角色占用的声音，
    # 避免「路人」听起来就是叶秋或孙翔；同时记下性别，轮换时男女交替。
    assigned = set(voices.values()) | {narrator}
    crowd_genders = {v: g for g, ids in bank_pools.items() for v in ids}
    if bank_all:
        # 群杂优先用预留的「朗读」音色；播音腔留给有名有姓的次要角色
        crowd_source = [v for v in _style_of(bank_all, "read") if v in reserved_for_crowd] + \
                       [v for v in bank_all if v not in reserved_for_crowd]
        crowd_pool = [v for v in crowd_source if v not in assigned] or crowd_source
    else:
        crowd_pool = [v for v in preset_names if v not in assigned]
    # 别名（叶秋/叶修、经理/陈夜辉）共用同一个音色
    for name, info in characters.items():
        base_voice = voices.get(name)
        if not base_voice:
            continue
        for alias in info.get("aliases") or []:
            if alias and alias != name:
                voices.setdefault(alias, base_voice)
    if not crowd_pool:
        crowd_pool = [v for v in dict.fromkeys(voices.values()) if v != narrator]

    cast = {
        "version": CAST_VERSION,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "narrator": narrator,
        "voice_bank": (bank or {}).get("_path", ""),
        "crowd_pool": crowd_pool,
        "crowd_genders": crowd_genders,
        "voices": voices,
        "characters": characters,
    }

    dup = [v for v, n in usage.items() if n > 1]
    if dup:
        log.info(f"  ⚠️ 音色数量不足，以下音色被复用: {', '.join(sorted(dup))}")
    return cast


def _cloud_cast(characters, config, tts_cfg):
    """云端 TTS 的音色是服务商 id（nova / onyx …），不涉及参考音文件。"""
    pools = tts_cfg.get("cloud_voices") or {}
    pools = {g: [str(v) for v in (pools.get(g) or [])] for g in ("female", "male", "unknown")}
    if not any(pools.values()):
        pools = {"female": ["nova", "shimmer"], "male": ["onyx", "echo"], "unknown": ["alloy"]}

    overrides = config.config.get("character_voices") or {}
    known = {v for ids in pools.values() for v in ids}
    for name, voice in overrides.items():
        if voice and voice not in known:
            log.info(f"  ⚠️ character_voices[{name}]={voice} 不在 cloud_voices 里，云端可能拒绝该音色")
    default_pool = pools["female"] or pools["unknown"] or ["alloy"]
    narrator = overrides.get("旁白") or default_pool[0]
    voices = {"旁白": narrator}
    usage = Counter({narrator: 1})

    for name, info in characters.items():
        if name == "旁白":
            continue
        voice = overrides.get(name)
        if not voice:
            gender = info.get("gender", "unknown")
            pool = pools.get(gender) or pools["unknown"] or default_pool
            free = [v for v in pool if v not in usage]
            voice = free[0] if free else min(pool, key=lambda v: usage[v])
        voices[name] = voice
        usage[voice] += 1

    crowd_genders = {v: g for g, ids in pools.items() for v in ids}
    assigned = set(voices.values())
    crowd_pool = [v for v in dict.fromkeys(sum(pools.values(), [])) if v not in assigned]
    if not crowd_pool:
        crowd_pool = [v for v in dict.fromkeys(voices.values()) if v != narrator]

    return {
        "version": CAST_VERSION,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "narrator": narrator,
        "voice_bank": "",
        "crowd_pool": crowd_pool,
        "crowd_genders": crowd_genders,
        "voices": voices,
        "characters": characters,
    }


CROWD_CHARACTERS = {
    "众人", "路人", "群杂", "群众", "旁观者", "观众", "人们", "大家", "未知",
    "学生们", "同学们", "士兵们", "围观群众", "吃瓜群众",
}


def _is_crowd(name: str) -> bool:
    if not name:
        return False
    if name in CROWD_CHARACTERS:
        return True
    return any(name.startswith(p) for p in ("众人", "路人", "群杂", "群众", "观众", "围观"))


def _stable_index(name: str, size: int) -> int:
    """按名字算一个稳定下标，保证同一角色每次分配到的音色一致。"""
    if size <= 0:
        return 0
    digest = hashlib.sha1((name or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def apply_cast(lines: Iterable, cast: dict, narrator_fallback: bool = True) -> List[str]:
    """把音色写回每一行，返回角色表里查不到的角色名列表。

    「众人 / 路人」这类群体角色逐条轮换音色：同一场景里多次群杂说话时，
    听感上是不同的人在说，而不是一个人从头念到尾。
    """
    voices = (cast or {}).get("voices", {})
    narrator = (cast or {}).get("narrator", "冰糖")
    explicit_pool = [v for v in (cast.get("crowd_pool") or []) if v]
    crowd_pool = explicit_pool or [
        v for v in dict.fromkeys(voices.values()) if v and v != narrator
    ]
    crowd_genders = cast.get("crowd_genders") or {}
    male = [v for v in crowd_pool if crowd_genders.get(v) == "male"]
    female = [v for v in crowd_pool if crowd_genders.get(v) == "female"]
    crowd_seq: List[str] = []
    if male and female:
        # 男女交替，听起来像不同的人
        for i in range(max(len(male), len(female))):
            if i < len(female):
                crowd_seq.append(female[i])
            if i < len(male):
                crowd_seq.append(male[i])
    if not crowd_seq:
        crowd_seq = list(crowd_pool)
    crowd_i = 0
    prev_crowd = None
    unknown: List[str] = []
    for line in lines:
        name = line.character
        voice = voices.get(name)
        crowd = _is_crowd(name)
        if not voice and not crowd:
            unknown.append(name)
        if crowd and crowd_seq:
            voice = crowd_seq[crowd_i % len(crowd_seq)]
            if prev_crowd and voice == prev_crowd and len(crowd_seq) > 1:
                voice = crowd_seq[(crowd_i + 1) % len(crowd_seq)]
            crowd_i += 1
            prev_crowd = voice
        elif not voice:
            # 角色表外的独立人物（如只出现一次的「张秀才」）：按名字稳定地分一个群杂音色，
            # 比回退旁白更像独立角色，而且每次重跑结果一致。没有专门群杂池时才回退旁白。
            if explicit_pool:
                voice = explicit_pool[_stable_index(name, len(explicit_pool))]
            else:
                voice = narrator if narrator_fallback else ""
        line.voice_id = voice
    return sorted(set(unknown))


def save_cast(cast: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_cast(path: Path) -> Optional[dict]:
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and "voices" in data else None


def print_cast(cast: dict, max_rows: int = 60) -> None:
    voices = (cast or {}).get("voices", {})
    log.info(f"  🎭 全书音色分配（{len(voices)} 个角色）:")
    for i, (name, voice) in enumerate(voices.items()):
        if i >= max_rows:
            log.info(f"     … 其余 {len(voices) - max_rows} 个角色略")
            break
        info = (cast.get("characters") or {}).get(name, {})
        gender = {"male": "男", "female": "女"}.get(info.get("gender", ""), "")
        tag = f" [{gender}]" if gender else ""
        log.info(f"     {name}{tag} -> {voice}")
