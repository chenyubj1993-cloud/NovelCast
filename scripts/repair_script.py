"""修复已有剧本：拆开旁白里夹带的对白，可选让 LLM 复核「未知」说话人。

用法：
    python scripts/repair_script.py output/某书_有声书/002_xxx_script.json            # 只预览
    python scripts/repair_script.py ... --write                                       # 写回
    python scripts/repair_script.py ... --review --write                              # 写回并调用 LLM 复核未知
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from novelcast.log import log

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.segment_rules import count_bad_lines, postprocess_lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="修剧本：拆分旁白中的对白、复核未知说话人")
    parser.add_argument("script", help="*_script.json 路径")
    parser.add_argument("--review", action="store_true", help="调用 LLM 复核「未知」说话人")
    parser.add_argument("--write", action="store_true", help="写回文件（默认只预览）")
    return parser


def load_characters(script_path: Path) -> dict:
    roster_path = script_path.parent / "characters.json"
    if roster_path.exists():
        data = json.loads(roster_path.read_text(encoding="utf-8"))
        return data.get("characters", {})
    return {}


def main() -> int:
    args = build_parser().parse_args()
    script_path = Path(args.script)
    data = json.loads(script_path.read_text(encoding="utf-8"))
    lines = data.get("lines", [])

    characters = load_characters(script_path)
    names = set(characters)
    names |= {l.get("character") for l in lines if l.get("character") not in (None, "", "旁白", "未知")}

    [dict(l) for l in lines]
    fixed, stats = postprocess_lines(lines, sorted(names))

    log.info(f"行数: {len(lines)} -> {len(fixed)}")
    log.info(f"拆分旁白中的对白: {stats['split']} 行, 未知说话人: {stats['unknown']} 行")
    log.info(f"旁白仍含引号: {count_bad_lines(lines)} -> {count_bad_lines(fixed)}")

    if args.review:
        from novelcast.config_manager import get_config
        from novelcast.llm_review import review_unknown

        fixed, reviewed = review_unknown(fixed, characters, get_config())
        log.info(f"LLM 复核修正: {len(reviewed)} 处")
        for idx, old, new in reviewed:
            log.info(f"  {idx}: {old} -> {new}")

    log.info("\n拆分样例（未知说话人的对白及上下文）：")
    shown = 0
    for i, line in enumerate(fixed):
        if line["character"] != "未知" or shown >= 4:
            continue
        shown += 1
        for j in range(max(0, i - 1), min(len(fixed), i + 2)):
            mark = ">>" if j == i else "  "
            log.info(f"  {mark} {j} [{fixed[j]['character']}] {fixed[j]['text'][:50]}")
        log.info()

    if args.write:
        backup = script_path.with_suffix(script_path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        data["lines"] = fixed
        tmp = script_path.with_suffix(script_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, script_path)
        log.info(f"\n已写回: {script_path}")
    else:
        log.info("\n（预览模式，未写回；加 --write 生效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
