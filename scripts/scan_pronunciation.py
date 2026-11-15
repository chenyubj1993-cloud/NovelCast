# -*- coding: utf-8 -*-
"""扫描剧本/文本里的多音字风险词，生成 config/pronunciation.json 建议。

用法：
    python scripts/scan_pronunciation.py output/全职高手_有声书/002_*_script.json
    python scripts/scan_pronunciation.py input/某书.txt --limit 200
    python scripts/scan_pronunciation.py ... --llm --write   # 让 DeepSeek 判断读音并写回

不带 --llm 时只列出候选词和它在词典里的所有读音，供人工确认。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from novelcast.log import log

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    import jieba
    import pypinyin
    from pypinyin import Style
except ImportError as exc:  # pragma: no cover
    log.info(f"缺少依赖：{exc}（需要 jieba / pypinyin）")
    raise SystemExit(1)

from novelcast.config_manager import get_config
from novelcast.pronunciation import DEFAULT_PATH, load_mapping


def iter_texts(path, limit=None):
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        lines = data.get("lines", [])
        for line in lines[: limit or len(lines)]:
            yield line.get("text", "")
    else:
        with open(path, "r", encoding="utf-8") as f:
            block = []
            for line in f:
                if not line.strip():
                    if block:
                        yield "".join(block)
                        block = []
                    continue
                block.append(line.strip())
            if block:
                yield "".join(block)


def readings_of(word):
    """返回 [{char, default, all:[...]}]，只保留多音字。"""
    detail = pypinyin.pinyin(word, heteronym=True, style=Style.TONE3, neutral_tone_with_five=True)
    plain = pypinyin.pinyin(word, style=Style.TONE3, neutral_tone_with_five=True)
    out = []
    for ch, alts, default in zip(word, detail, plain):
        if not ("\u4e00" <= ch <= "\u9fff"):
            continue
        if len(alts) > 1:
            out.append({"char": ch, "default": default[0].upper(), "all": [a.upper() for a in alts]})
    return out


def collect(texts, limit_words=200):
    seen = {}
    for text in texts:
        for tok in jieba.cut(text):
            tok = tok.strip()
            if len(tok) < 2 or not all("\u4e00" <= c <= "\u9fff" for c in tok):
                continue
            if tok in seen:
                continue
            info = readings_of(tok)
            if info:
                ctx = text[max(0, text.find(tok) - 12): text.find(tok) + len(tok) + 12]
                seen[tok] = {"word": tok, "chars": info, "context": ctx}
                if len(seen) >= limit_words:
                    return list(seen.values())
    return list(seen.values())


def ask_llm(cands, config):
    """让 DeepSeek 为每个候选词选读音，返回 {word: 'CHONG2 QING4'}。"""
    from novelcast.dialogue_splitter import get_llm_client

    client = get_llm_client(config)
    prompt = (
        "你是中文配音校对。下面是小说里含多音字的词及其上下文，"
        "请判断每个词在上下文中的正确读音，按字给出带声调拼音（数字声调，大写，空格分隔）。\n"
        "只输出 JSON 对象：{\"词\": \"PIN1 YIN1\"}，不要解释。\n\n"
        + json.dumps(cands, ensure_ascii=False, indent=1)
    )
    resp = client.chat.completions.create(
        model=config.llm_api.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    content = resp.choices[0].message.content or ""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        data = json.loads(content[start:end + 1])
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="*_script.json 或 txt")
    ap.add_argument("--limit", type=int, default=0, help="只看前 N 行/段")
    ap.add_argument("--max-words", type=int, default=200)
    ap.add_argument("--llm", action="store_true", help="用 DeepSeek 判断读音")
    ap.add_argument("--write", action="store_true", help="合并写入 config/pronunciation.json")
    args = ap.parse_args()

    paths = glob.glob(args.path)
    if not paths:
        raise SystemExit(f"找不到 {args.path}")
    texts = list(iter_texts(paths[0], args.limit or None))
    cands = collect(texts, args.max_words)
    if not cands:
        log.info("没有发现多音字风险词")
        return

    for c in cands:
        chars = "；".join(f"{x['char']} 默认{x['default']} 可选{'/'.join(x['all'])}" for x in c["chars"])
        log.info(f"- {c['word']}: {chars}\n  上下文：{c['context']}")

    if args.llm:
        config = get_config()
        chosen = ask_llm(cands, config)
        if not chosen:
            log.info("LLM 没有返回可用结果")
            return
        log.info("\n建议读音：")
        for k, v in chosen.items():
            log.info(f"  {k}: {v}")
        if args.write:
            load_mapping() or {}
            if os.path.exists(DEFAULT_PATH):
                with open(DEFAULT_PATH, "r", encoding="utf-8") as f:
                    doc = json.load(f)
            else:
                doc = {"words": {}}
            doc.setdefault("words", {}).update(chosen)
            with open(DEFAULT_PATH, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            log.info(f"已写入 {DEFAULT_PATH}（{len(chosen)} 条）")


if __name__ == "__main__":
    main()
