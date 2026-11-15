"""确定性剧本修复规则。

LLM 经常把「旁白 + 引号对白」写进同一段，或者把没把握说话人的对白直接
标成「旁白」。这里用规则做兜底：

1. 旁白段落里出现成对引号 -> 拆成 旁白 / 对白 / 旁白 多段；
2. 对白说话人优先从引号前的「名字 + 说/问/道…」里取；
3. 取不到就标成「未知」，交给人工或二次 LLM 复核，绝不再混进旁白。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Tuple

QUOTE_RE = re.compile(r"[“\"]([^“”\"]+)[”\"]")

SPEECH_VERBS = (
    "说道|问道|喊道|叫道|答道|笑道|骂道|吼道|喝道|低声道|沉声道|"
    "说|问|道|喊|叫|答|笑|骂|吼"
)
SPEECH_RE = re.compile(r"(?:%s)" % SPEECH_VERBS)
TAIL_AFTER_NAME_RE = re.compile(r"^[^。！？；\n]{0,10}?(?:%s)[：:]?\s*$" % SPEECH_VERBS)
HEAD_BEFORE_NAME_RE = re.compile(r"^[，,。]?\s*([\u4e00-\u9fa5]{2,6}?)(?:%s)" % SPEECH_VERBS)

UNKNOWN = "未知"
NARRATOR = "旁白"


def _clean(text: str) -> str:
    return text.strip().strip("，,、 ").strip()


def _attribute(before: str, after: str, names: Sequence[str]) -> str:
    """从引号前后的叙述里推断说话人，推断不出返回空串。"""
    before_tail = before[-30:]
    after_head = after[:20]

    for name in sorted(names, key=len, reverse=True):
        if not name:
            continue
        # 「叶秋说：」「苏沐橙笑着说道：」——名字和动词之间不能有标点，
        # 否则多半是宾语（「瞅到了犹豫的叶秋，气冲冲地问道」）。
        if name in before_tail:
            idx = before_tail.rfind(name)
            tail = before_tail[idx + len(name):].strip()
            if (
                tail
                and len(tail) <= 6
                and not any(ch in tail for ch in "，,。！？；：")
                and re.fullmatch(r"(?:%s)[：:]?" % SPEECH_VERBS, tail)
            ):
                return name
        # 「说道：」后紧跟「叶秋……」
        if name in after_head:
            head = after_head[: after_head.find(name)]
            if not head.strip("，,。 "):
                return name
    return ""


def split_line(
    character: str, text: str, emotion: str, names: Sequence[str]
) -> List[Tuple[str, str, str]]:
    """把一行拆成若干 (character, text, emotion)。不需要拆时原样返回。"""
    if not QUOTE_RE.search(text):
        return [(character, text, emotion)]

    # 非旁白行如果整行就是一句对白，保持原样
    stripped = text.strip()
    m_full = QUOTE_RE.fullmatch(stripped)
    if m_full and character not in (NARRATOR, ""):
        return [(character, stripped, emotion)]

    pieces: List[Tuple[str, str, str]] = []
    pos = 0
    for match in QUOTE_RE.finditer(text):
        before = text[pos:match.start()]
        quote = match.group(1).strip()
        after = text[match.end():]
        if before.strip():
            pieces.append((NARRATOR, _clean(before), emotion))
        if quote:
            speaker = _attribute(before, after, names) or UNKNOWN
            pieces.append((speaker, quote, emotion))
        pos = match.end()

    tail = text[pos:]
    if tail.strip():
        pieces.append((NARRATOR, _clean(tail), emotion))

    if not pieces:
        return [(character, text, emotion)]

    # 合并相邻的旁白碎片
    merged: List[Tuple[str, str, str]] = []
    for piece in pieces:
        if not piece[1]:
            continue
        if merged and merged[-1][0] == piece[0] == NARRATOR:
            merged[-1] = (NARRATOR, merged[-1][1] + "，" + piece[1], merged[-1][2])
        else:
            merged.append(piece)
    return merged


def postprocess_lines(
    lines: Iterable[Dict[str, str]], names: Sequence[str]
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """修复整章结果，返回 (新行列表, 统计)。"""
    names = [n for n in names if n and n not in (NARRATOR, UNKNOWN, "众人")]
    out: List[Dict[str, str]] = []
    stats = {"split": 0, "unknown": 0, "kept": 0}
    for line in lines:
        character = (line.get("character") or NARRATOR).strip()
        text = (line.get("text") or "").strip()
        emotion = (line.get("emotion") or "neutral").strip()
        if not text:
            continue
        pieces = split_line(character, text, emotion, names) if character == NARRATOR else [(character, text, emotion)]
        if len(pieces) > 1:
            stats["split"] += 1
        for c, t, e in pieces:
            if c == UNKNOWN:
                stats["unknown"] += 1
            out.append({"character": c, "text": t, "emotion": e})
    stats["kept"] = len(out)
    return out, stats


def count_bad_lines(lines: Sequence[Dict[str, str]]) -> int:
    """统计仍是旁白却带引号的行数（质量指标）。"""
    return sum(1 for l in lines if l.get("character") == NARRATOR and QUOTE_RE.search(l.get("text", "")))
