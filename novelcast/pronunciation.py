"""多音字发音标注（IndexTTS-2.5 的 <字|拼音> 语法）。

用法：
    pronunciation.json 里维护 {"words": {"重庆": "CHONG2 QING4"}}，
    合成前 apply_pronunciation("重庆的夜") -> "<重|CHONG2><庆|QING4>的夜"。

只有 model_version 为 2.5 时才会启用；2.x 会把标注原样念出来。
"""
from __future__ import annotations

import json
import os
import re

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(_PROJECT_ROOT, "config", "pronunciation.json")

_cache = {"path": None, "mtime": None, "words": {}}


def load_mapping(path: str | None = None) -> dict:
    path = path or DEFAULT_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["words"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    words = data.get("words", data) if isinstance(data, dict) else {}
    if not isinstance(words, dict):
        words = {}
    _cache.update(path=path, mtime=mtime, words=words)
    return words


def mapping_version(path: str | None = None) -> str:
    """映射变化时让缓存失效。"""
    path = path or DEFAULT_PATH
    try:
        st = os.stat(path)
        return f"{st.st_mtime_ns:x}"
    except OSError:
        return "none"


def annotate_word(word: str, pinyin: str | None) -> str:
    """把词转成 <字|PINYIN> 序列；拼音按空格对齐到每个字。"""
    if not pinyin:
        return word
    pinyin = pinyin.strip().upper()
    if "<" in pinyin:
        return pinyin  # 已经是完整标注
    py = [p for p in re.split(r"[\s]+", pinyin) if p]
    chars = list(word)
    if len(py) == 1 and len(chars) > 1:
        return f"<{word}|{py[0]}>"
    if len(py) != len(chars):
        # 对不齐就整词标注，交给模型自己切分
        return f"<{word}|{' '.join(py)}>"
    return "".join(f"<{c}|{p}>" for c, p in zip(chars, py))


_ANNOTATED = re.compile(r"<[^<>|]+\|[^<>]+>")


def apply_pronunciation(text: str, words: dict | None = None) -> str:
    if not text:
        return text
    words = words if words is not None else load_mapping()
    if not words:
        return text
    # 长的词优先，避免「重庆」被「重」抢先
    for word in sorted(words, key=len, reverse=True):
        if not word or word not in text:
            continue
        ann = annotate_word(word, words[word])
        if ann == word:
            continue
        # 已经标注过的片段不再重复包
        parts = []
        pos = 0
        for m in _ANNOTATED.finditer(text):
            if m.start() > pos:
                parts.append(text[pos:m.start()].replace(word, ann))
            parts.append(m.group(0))
            pos = m.end()
        parts.append(text[pos:].replace(word, ann))
        text = "".join(parts)
    return text


def enabled_for(config) -> bool:
    data = getattr(config, "config", config) or {}
    tts = data.get("tts", {}) if isinstance(data, dict) else {}
    provider = str(tts.get("provider") or "")
    version = str(tts.get("model_version") or "")
    # 标注语法只有本地 IndexTTS-2.5 认识；edge/云端会把 "<字|PINYIN>" 原样念出来
    return provider.startswith("indextts2") and version.startswith("2.5")
