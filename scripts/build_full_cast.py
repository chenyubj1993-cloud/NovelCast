"""通读全书，统计人物出场频次，一次性生成完整的 cast.json。

不把 500 万字塞进上下文，而是：
  1. jieba 词性标注，取 nr（人名）词频；
  2. 用「名字后 15 字内 他/她 的比例」推断性别；
  3. 按词频分主/次：前 N 个用原来的 edge 音色，其余用 AISHELL-3 真人音色库。

用法：
  python scripts/build_full_cast.py input\全职高手.epub --preview
  python scripts/build_full_cast.py input\全职高手.epub --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from novelcast.log import log

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novelcast.character_registry import is_valid_name  # noqa: E402
from novelcast.config_manager import ConfigManager  # noqa: E402
from novelcast.novel_reader import read_novel  # noqa: E402

EXTRA_STOP = {
    "他们", "她们", "我们", "你们", "自己", "大家", "众人", "有人", "别人", "对方",
    "这个", "那个", "这里", "那里", "此时", "这时", "那时", "现在", "当时", "之后", "然后",
    "什么", "怎么", "这样", "那样", "这么", "那么", "一下", "一直", "已经", "还是", "就是",
    "没有", "不是", "知道", "觉得", "看到", "听到", "发现", "心中", "心里", "脸上", "声音",
    "时候", "地方", "东西", "事情", "问题", "家伙", "小子", "老师", "学生", "老板",
    "玩家", "角色", "副本", "公会", "战队", "职业", "联盟", "比赛", "荣耀",
    "二人", "三人", "几人", "一人", "两人", "波涛", "明白", "寒烟柔", "千机伞",
}

TEAM_STOP = {
    "嘉世", "兴欣", "蓝雨", "蓝溪阁", "全明星", "轮回", "霸图", "微草", "呼啸",
    "虚空", "义斩", "百花", "三零一", "神奇", "皇风", "明青", "越云", "联盟", "荣耀",
}
SPEECH_RE = re.compile(r"(说|道|问|答|喊|叫|笑|叹|吼|骂|嚷|开口|回应|点头|皱眉)")


def speech_count(text: str, name: str, cap: int = 60) -> int:
    """名字后面紧跟说话/动作动词的次数——用来过滤战队名、公会名这类非人物。"""
    c = 0
    for m in re.finditer(re.escape(name), text):
        if SPEECH_RE.match(text, m.end()):
            c += 1
            if c >= cap:
                break
    return c
FEMALE_HINTS = ("女", "妈", "姐", "妹", "姑娘", "小姐", "夫人", "太太", "阿姨", "婆", "嫂", "妃", "后", "氏", "娘", "姑", "姨", "媳妇")
MALE_HINTS = ("爷", "哥", "弟", "叔", "伯", "先生", "少爷", "公子", "大帝", "陛下", "老头", "公", "老汉")
# 名字里带这些字的多半是女性（小翠、白灵、田小娥），比上下文代词更稳
FEMALE_NAME_CHARS = "翠娥灵英芳秀莲梅兰霞娟静丽敏燕玲珍凤婷媛"


def guess_gender(name: str) -> str:
    if any(h in name for h in FEMALE_HINTS):
        return "female"
    if any(h in name for h in MALE_HINTS):
        return "male"
    if any(ch in FEMALE_NAME_CHARS for ch in name):
        return "female"
    return "unknown"


def merge_aliases(counts: Counter) -> tuple[Counter, dict]:
    """把「嘉轩 / 白嘉轩」「子霖 / 鹿子霖」并成一个人，别名挂在长名下。"""
    items = sorted(counts.items(), key=lambda kv: (-len(kv[0]), -kv[1]))
    merged: Counter = Counter()
    aliases: dict = {}
    for name, c in items:
        target = None
        for cand in merged:
            if len(cand) > len(name) and cand.endswith(name):
                target = cand
                break
        if target:
            merged[target] += c
            aliases.setdefault(target, []).append(name)
        else:
            merged[name] = c
    return merged, aliases


def infer_gender_from_context(text: str, name: str, limit: int = 300) -> str:
    """名字后面 15 字内 他/她 的出现比例；中文小说里代词跟随主语，够用了。"""
    he = she = 0
    start = 0
    seen = 0
    while seen < limit:
        i = text.find(name, start)
        if i < 0:
            break
        window = text[i + len(name): i + len(name) + 15]
        he += window.count("他")
        she += window.count("她")
        start = i + len(name)
        seen += 1
    if he + she < 3:
        return "unknown"
    if she >= he * 1.5:
        return "female"
    if he >= she * 1.5:
        return "male"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("book")
    parser.add_argument("--config", default=str(ROOT / "config" / "settings.json"))
    parser.add_argument("--write", action="store_true", help="写入 output/<书名>/cast.json")
    parser.add_argument("--min-count", type=int, default=30, help="最少出现次数")
    parser.add_argument("--mains", type=int, default=6, help="主要角色数量")
    parser.add_argument("--top", type=int, default=40, help="预览前多少个")
    parser.add_argument("--gender-sample", type=int, default=300, help="每个名字取样多少处推断性别")
    args = parser.parse_args()

    import jieba.posseg as pseg

    config = ConfigManager(args.config)
    title, text = read_novel(args.book)
    log.info(f"📖 {title}：{len(text):,} 字，正在做词性标注…")

    counts: Counter = Counter()
    for word, flag in pseg.cut(text):
        if not flag.startswith("nr"):
            continue
        w = word.strip()
        if len(w) < 2 or len(w) > 4 or w in EXTRA_STOP:
            continue
        if not is_valid_name(w):
            continue
        counts[w] += 1

    VERB_SUFFIX = "说笑道问答喊叫叹吼骂嚷"
    merged: Counter = Counter()
    for name, c in counts.items():
        n = name
        while len(n) > 2 and n[-1] in VERB_SUFFIX:
            n = n[:-1]
        merged[n] += c
    counts = merged

    counts = Counter({
        k: v for k, v in counts.items()
        if v >= args.min_count and k not in TEAM_STOP
    })
    # 战队名/公会名往往没有「某某说道」的用法，用说话动词再筛一遍
    counts = Counter({k: v for k, v in counts.items() if speech_count(text, k) >= 2})
    counts, alias_map = merge_aliases(counts)
    log.info(f"🔎 候选人物 {len(counts)} 个")

    roster_path = ROOT / "output" / f"{title}_有声书" / "characters.json"
    known: dict = {}
    if roster_path.exists():
        try:
            known = json.loads(roster_path.read_text(encoding="utf-8")).get("characters", {})
        except Exception:  # noqa: BLE001
            known = {}

    characters = {}
    for i, (name, count) in enumerate(counts.most_common(), 1):
        gender = known.get(name, {}).get("gender") or guess_gender(name)
        if gender == "unknown":
            gender = infer_gender_from_context(text, name, args.gender_sample)
        characters[name] = {
            "name": name,
            "aliases": list(dict.fromkeys(
                list(known.get(name, {}).get("aliases", [])) + alias_map.get(name, [])
            )),
            "gender": gender,
            "age": known.get(name, {}).get("age", "unknown"),
            "role": "lead" if i <= args.mains else "minor",
            "description": "全文字频统计",
            "appearances": count,
        }

    for i, (name, count) in enumerate(counts.most_common(args.top), 1):
        c = characters[name]
        log.info(f"  {i:3d}. {name:<6} 提及={count:<6} 性别={c['gender']}")

    from novelcast.cast_manager import build_cast, print_cast, save_cast

    config.config["main_character_count"] = args.mains
    cast = build_cast({"characters": characters}, config)
    log.info()
    print_cast(cast)

    out_dir = ROOT / "output" / f"{title}_有声书"
    if not args.write:
        log.info(f"\n（预览模式，未写入；加 --write 保存到 {out_dir / 'cast.json'}）")
        return 0

    save_cast(cast, out_dir / "cast.json")
    (out_dir / "characters.json").write_text(
        json.dumps({"version": 1, "book": title, "characters": characters}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"\n💾 已写入 {out_dir / 'cast.json'} 与 characters.json（{len(characters)} 个角色）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
