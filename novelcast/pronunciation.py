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
BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "polyphones.json")
CURATED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "polyphones_curated.json")

# 语气助词、代词、轻声词：默认读音本来就对，钉住反而生硬（如 什么 -> SHEN2 ME5）
NEUTRAL_WORDS = frozenset({
    "什么", "那个", "这个", "哪个", "那么", "这么", "怎么", "怎样", "怎样",
    "一个", "一下", "一些", "时候", "意思", "我们", "你们", "他们", "她们",
    "它们", "咱们", "人们", "的", "了", "着", "过", "吧", "吗", "呢", "啊",
    "呀", "嘛", "哦", "嗯", "啦", "哇", "咯", "喽", "罢了", "而已",
})

_cache = {"path": None, "mtime": None, "words": {}}
_builtin = {"mtime": None, "words": {}}
_curated = {"mtime": None, "words": {}}


def _load_json_table(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    words = data.get("words", {}) if isinstance(data, dict) else {}
    return words if isinstance(words, dict) else {}


def _load_builtin() -> dict:
    """自动生成的常用多音字词表（phrase-pinyin-data + jieba 词频，约 300 词）。"""
    try:
        mtime = os.path.getmtime(BUILTIN_PATH)
    except OSError:
        return {}
    if _builtin["mtime"] != mtime:
        _builtin.update(mtime=mtime, words=_load_json_table(BUILTIN_PATH))
    return _builtin["words"]


def _load_curated() -> dict:
    """普通话水平测试多音字表（人工整理，约 2,000 词，覆盖优先于自动表）。"""
    try:
        mtime = os.path.getmtime(CURATED_PATH)
    except OSError:
        return {}
    if _curated["mtime"] != mtime:
        _curated.update(mtime=mtime, words=_load_json_table(CURATED_PATH))
    return _curated["words"]


def _keep(word: str) -> bool:
    """过滤语气助词/代词/轻声词，以及单字（脱离上下文标注没有意义）。"""
    return bool(word) and len(word) > 1 and word not in NEUTRAL_WORDS


def load_mapping(path: str | None = None) -> dict:
    """自动表打底 → 普测人工表覆盖 → config/pronunciation.json 最终覆盖。"""
    merged = {w: p for w, p in _load_builtin().items() if _keep(w)}
    merged.update({w: p for w, p in _load_curated().items() if _keep(w)})
    path = path or DEFAULT_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return merged
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["words"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return merged
    words = data.get("words", data) if isinstance(data, dict) else {}
    if not isinstance(words, dict):
        words = {}
    merged.update(words)
    _cache.update(path=path, mtime=mtime, words=merged)
    return merged


def mapping_version(path: str | None = None) -> str:
    """映射变化时让缓存失效。"""
    path = path or DEFAULT_PATH
    try:
        builtin = f"{int(os.path.getmtime(BUILTIN_PATH)):x}-{int(os.path.getmtime(CURATED_PATH)):x}"
    except OSError:
        builtin = "none"
    try:
        st = os.stat(path)
        return f"{builtin}-{st.st_mtime_ns:x}"
    except OSError:
        return f"{builtin}-none"


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
        if py[0] == "*":
            return word
        return f"<{word}|{py[0]}>"
    if len(py) != len(chars):
        # 对不齐就整词标注，交给模型自己切分；带 * 的对不齐说明表写错了，直接跳过
        if any(p == "*" for p in py):
            return word
        return f"<{word}|{' '.join(py)}>"
    # * 表示这个字保持原样，只钉住词里需要的字（如 拽什么拽 -> ZHUA3 * *）
    return "".join(c if p == "*" else f"<{c}|{p}>" for c, p in zip(chars, py))


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
    if not isinstance(data, dict):
        data = {}
    pron = data.get("pronunciation", {})
    if isinstance(pron, dict) and pron.get("enabled") is False:
        return False
    tts = data.get("tts", {}) if isinstance(data, dict) else {}
    provider = str(tts.get("provider") or "")
    version = str(tts.get("model_version") or "")
    # 标注语法只有本地 IndexTTS-2.5 认识；edge/云端会把 "<字|PINYIN>" 原样念出来
    return provider.startswith("indextts2") and version.startswith("2.5")
