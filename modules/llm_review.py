"""用 LLM 复核「未知」说话人：只判定谁在说话，不改写任何文字。"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Sequence, Tuple

REVIEW_SYSTEM = "你是有声书剧本校对，只输出 JSON 数组，不要任何解释。"

REVIEW_PROMPT = """下面是一段小说剧本，其中有些对白的说话人标成了「未知」。
请根据上下文判断每句对白真正的说话人。

## 角色表（只能从这里选）：
{roster}

## 待判断的对白（id 是行号）：
{items}

## 要求：
1. 依据：紧邻的叙述句（如「叶秋问道：」）、上下句的对话轮次、称呼语。
2. 只能填角色表里的名字；确实无法判断就填「未知」。
3. 不要改写对白文字，不要新增条目。
4. 输出格式：[{{"id": 12, "speaker": "叶秋"}}, ...]
"""


def _build_items(lines: Sequence[Dict[str, str]], indices: Sequence[int], context: int = 2) -> str:
    blocks = []
    for idx in indices:
        start = max(0, idx - context)
        end = min(len(lines), idx + context + 1)
        ctx = []
        for j in range(start, end):
            mark = ">>" if j == idx else "  "
            ctx.append(f"{mark} {j} [{lines[j]['character']}] {lines[j]['text']}")
        blocks.append("\n".join(ctx))
    return "\n\n".join(blocks)


def review_unknown(
    lines: List[Dict[str, str]],
    characters: Dict[str, dict],
    config=None,
    context: int = 2,
    batch_size: int = 12,
) -> Tuple[List[Dict[str, str]], List[Tuple[int, str, str]]]:
    """返回 (新行列表, [(行号, 原角色, 新角色)])。"""
    from modules.config_manager import get_config

    config = config or get_config()
    indices = [i for i, l in enumerate(lines) if l.get("character") == "未知"]
    if not indices:
        return lines, []

    roster_lines = []
    for name, info in characters.items():
        bits = [name]
        for key in ("gender", "age", "role", "description"):
            value = (info or {}).get(key)
            if value:
                bits.append(str(value))
        roster_lines.append("- " + " / ".join(bits))
    roster_text = "\n".join(roster_lines) or "（无）"

    from openai import OpenAI
    import httpx2

    # 系统代理是 socks=...，httpx2 会解析成 socks4:// 并报错；复核请求直连即可
    client = OpenAI(
        base_url=config.llm_api.base_url,
        api_key=config.llm_api.api_key,
        http_client=httpx2.Client(trust_env=False, timeout=90),
    )
    changes: List[Tuple[int, str, str]] = []

    for start in range(0, len(indices), batch_size):
        batch = indices[start:start + batch_size]
        prompt = REVIEW_PROMPT.format(roster=roster_text, items=_build_items(lines, batch, context))
        response = client.chat.completions.create(
            model=config.llm_api.model,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        text = response.choices[0].message.content or ""
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        for item in data:
            try:
                idx = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            speaker = str(item.get("speaker") or "").strip()
            if idx in batch and speaker in characters and speaker != "未知":
                old = lines[idx]["character"]
                if old != speaker:
                    lines[idx] = dict(lines[idx], character=speaker)
                    changes.append((idx, old, speaker))
    return lines, changes
