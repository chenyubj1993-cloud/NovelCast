"""剧本完整性校验：原文与标注结果逐字对齐，定位丢字。

原来的覆盖率只比较总字数，丢了哪一段、丢在开头还是结尾都看不出来。
SequenceMatcher 能给出原文中未被任何一行覆盖的区间（gap），据此可以：
1. 打印精确的缺失位置，便于人工核对；
2. 把结尾被截断的文本补成一行旁白，避免音频少一句。

注意：LLM 标注时通常会把对白两侧的引号去掉（文字搬进 character/text，
引号本身不再保留），这类纯标点差异不算丢字，统计时单独排除。
"""

from __future__ import annotations

import bisect
import difflib
import re
from typing import Any, Dict, List, Sequence

# 引号、标点、空白：TTS 不会读出来，缺失它们不影响内容
_PUNCT = set(
    "“”‘’「」『』（）()《》〈〉【】[]{}"
    "，,。.！!？?；;：:、—–…·～~\"'` "
    "\n\r\t"
)


def _text(item: Any) -> str:
    """兼容 DialogueLine 与 dict 两种行结构。"""
    if hasattr(item, "text"):
        return item.text or ""
    return item.get("text", "") or ""


def _substantive(text: str) -> str:
    """去掉标点/空白后的实际内容。"""
    return "".join(ch for ch in text if ch not in _PUNCT)


def alignment(original: str, lines: Sequence[Any]) -> Dict[str, Any]:
    """逐字对齐，返回覆盖率与缺失区间。

    gaps 只保留含实际文字的缺失；纯标点差异计入 punctuation_chars。
    """
    joined = "".join(_text(line) for line in lines)
    matcher = difflib.SequenceMatcher(None, original, joined, autojunk=False)
    opcodes = matcher.get_opcodes()
    gaps: List[Dict[str, Any]] = []
    punctuation_chars = 0
    for tag, i1, i2, j1, _j2 in opcodes:
        if tag not in ("delete", "replace") or i2 <= i1:
            continue
        chunk = original[i1:i2]
        substantive = _substantive(chunk)
        if not substantive:
            punctuation_chars += len(chunk)
            continue
        gaps.append({
            "start": i1,
            "end": i2,
            "joined_start": j1,
            "text": chunk,
            "kind": tag,
        })
    # 剧本里比原文多出来的内容：LLM 重复输出时这里会出现
    extra_chars = 0
    extra_spans = 0
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "insert" or j2 <= j1:
            continue
        piece = _substantive(joined[j1:j2])
        if piece:
            extra_chars += len(piece)
            extra_spans += 1

    return {
        "original_chars": len(original),
        "output_chars": len(joined),
        "coverage": (len(joined) / len(original)) if original else 1.0,
        "missing_chars": sum(len(_substantive(gap["text"])) for gap in gaps),
        "missing_spans": len(gaps),
        "punctuation_chars": punctuation_chars,
        "extra_chars": extra_chars,
        "extra_spans": extra_spans,
        "content_coverage": _content_coverage(original, gaps),
        "gaps": gaps,
    }


def _content_coverage(original: str, gaps: Sequence[Dict[str, Any]]) -> float:
    """按“实际文字”算覆盖率，引号等标点不计入。"""
    total = len(_substantive(original))
    if not total:
        return 1.0
    missing = sum(len(_substantive(gap["text"])) for gap in gaps)
    return max(0.0, (total - missing) / total)


def repair_tail(original: str, lines: List[Any], character: str = "旁白", max_chars: int = 2000) -> int:
    """如果原文结尾整段没被覆盖，补成一行旁白，返回补回的字符数。

    只处理「结尾 + 纯删除 + 有实际文字」的情况：替换型 gap 说明文本被改写，
    直接补会重复。
    """
    report = alignment(original, lines)
    if not report["gaps"]:
        return 0
    last = report["gaps"][-1]
    if last["kind"] != "delete" or last["end"] != len(original):
        return 0
    missing = last["text"].strip()
    if not missing or len(missing) > max_chars:
        return 0

    from modules.dialogue_splitter import DialogueLine

    lines.append(DialogueLine(character=character, text=missing, emotion="calm", voice_id=""))
    return len(missing)


def format_gap(gap: Dict[str, Any]) -> str:
    """把缺失区间格式化成一行日志。"""
    text = gap["text"].replace("\n", " ")
    if len(text) > 60:
        text = text[:57] + "…"
    return f"@{gap['start']} [{gap['kind']}] …{text}…"


_ATTRIBUTION_RE = re.compile(r"^[\u4e00-\u9fa5]{1,8}(?:说|问|道|答|喊|叫|着)(?:道)?$")


def _clean_attribution(text: str) -> str:
    core = text.strip().strip("“”‘’\"'「」『』")
    return core.rstrip("：:，,。.；; ")


def _extract_attributions(text: str) -> List[str]:
    """从缺失片段里提取「XX说/问」候选。

    gap 通常长这样：`”经理说。 “`——包含前一句的收尾引号、提示语、
    后一句的开头引号。直接 strip 会因为结尾的「…」匹配不上，
    所以这里按引号成对挖出中间的短句再校验。
    """
    found: List[str] = []
    for raw in re.findall(r"[”\"]([^”\"“”]{1,12}?)[。，,]?\s*[“\"]", text):
        core = _clean_attribution(raw)
        if _ATTRIBUTION_RE.match(core):
            found.append(core)
    if not found:
        core = _clean_attribution(text)
        if _ATTRIBUTION_RE.match(core):
            found.append(core)
    return found


def repair_attributions(original: str, lines: List[Any]) -> int:
    """LLM 把「”朱先生问：“」整段吃掉时，补回一行旁白「朱先生问」，返回补回条数。"""
    report = alignment(original, lines)
    if not report["gaps"]:
        return 0
    from modules.dialogue_splitter import DialogueLine

    fixed = 0
    for gap in sorted(report["gaps"], key=lambda g: g.get("joined_start", g["start"]), reverse=True):
        if gap["kind"] != "delete":
            continue
        candidates = _extract_attributions(gap["text"])
        if not candidates:
            continue
        core = candidates[0]
        # 用剧本内的偏移定位：缺失点落在哪一行之前，就插在那一行前面
        starts: List[int] = []
        pos = 0
        for line in lines:
            starts.append(pos)
            pos += len(_text(line))
        idx = bisect.bisect_left(starts, gap.get("joined_start", gap["start"]))
        lines.insert(idx, DialogueLine(character="旁白", text=core, emotion="neutral", voice_id=""))
        fixed += 1
    return fixed


def _character(item: Any) -> str:
    if hasattr(item, "character"):
        return item.character or ""
    return (item or {}).get("character", "") or ""


def repair_narration(original: str, lines: List[Any], max_chars: int = 40) -> int:
    """补回夹在两段对白之间、被 LLM 整段吃掉的短旁白。

    形如 `”孙翔瞪大了眼。“`：不是「XX说」，但确实是叙述，丢了会少一个动作。
    只在片段足够短（≤ max_chars）且以中文为主时补，避免把改写当成丢失。
    """
    report = alignment(original, lines)
    if not report["gaps"]:
        return 0
    from modules.dialogue_splitter import DialogueLine

    fixed = 0
    for gap in sorted(report["gaps"], key=lambda g: g.get("joined_start", g["start"]), reverse=True):
        if gap["kind"] != "delete":
            continue
        inner = gap["text"].strip().strip("“”‘’\"'「」『』\n\r\t ")
        inner = inner.rstrip("：:，,；; ")
        if not (2 <= len(inner) <= max_chars):
            continue
        cjk = sum(1 for ch in inner if "\u4e00" <= ch <= "\u9fa5")
        if cjk < len(inner) * 0.5:
            continue
        starts: List[int] = []
        pos = 0
        for line in lines:
            starts.append(pos)
            pos += len(_text(line))
        idx = bisect.bisect_left(starts, gap.get("joined_start", gap["start"]))
        lines.insert(idx, DialogueLine(character="旁白", text=inner, emotion="neutral", voice_id=""))
        fixed += 1
    return fixed


def dedupe_adjacent(lines: Sequence[Any], min_chars: int = 6) -> tuple:
    """删掉 LLM 连续重复输出的同一句（同角色、去标点后完全一致）。

    LLM 偶尔会把同一句吐两遍（尤其跨 chunk 时把上一段末尾又抄一次），
    两行文字完全一样、角色也一样，属于确定的重复，直接删掉。
    返回 (新行列表, 删除行数)。
    """
    out: List[Any] = []
    removed = 0
    for line in lines:
        body = _substantive(_text(line))
        if out and len(body) >= min_chars:
            prev = _substantive(_text(out[-1]))
            if body == prev and _character(line) == _character(out[-1]):
                removed += 1
                continue
        out.append(line)
    return out, removed
