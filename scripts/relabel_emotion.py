"""给已有剧本补情绪标签（只改 emotion，不动文本）。

    python scripts/relabel_emotion.py "output/全职高手_有声书/002_*_script.json"
    python scripts/relabel_emotion.py ... --write
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.config_manager import get_config
from modules.emotion_review import review_emotions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scripts", nargs="+", help="剧本 json，支持通配符")
    parser.add_argument("--write", action="store_true", help="写回文件（默认只预览）")
    parser.add_argument("--batch-size", type=int, default=15)
    args = parser.parse_args()

    config = get_config()
    files = []
    for pattern in args.scripts:
        files.extend(sorted(glob.glob(pattern)))
    if not files:
        print("没有匹配到剧本文件")
        return 1

    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        lines = data.get("lines") or []
        before = Counter((l.get("emotion") or "neutral") for l in lines)
        lines, changes = review_emotions(list(lines), config=config, batch_size=args.batch_size)
        after = Counter((l.get("emotion") or "neutral") for l in lines)
        print(f"\n{os.path.basename(path)}: {len(lines)} 行，改动 {len(changes)} 行")
        print("  改前:", dict(before))
        print("  改后:", dict(after))
        for idx, old, new in changes:
            print(f"    {idx} [{lines[idx]['character']}] {old} -> {new} | {lines[idx]['text'][:34]}")
        if args.write and changes:
            data["lines"] = lines
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            print(f"  ✅ 已写回 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
