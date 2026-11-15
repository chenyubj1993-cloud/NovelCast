"""用 LLM 给「neutral」的剧本行补情绪标签：只挑明显该有语气的行，拿不准不动。"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Sequence, Tuple

EMOTION_SYSTEM = "你是有声书导演，只输出 JSON 数组，不要任何解释。"

EMOTION_PROMPT = """下面是一段小说剧本，每行格式：行号 [角色] (情绪) 文本。
其中情绪标为 neutral 的行，有一部分其实读起来语气明显不同。请只挑出这些行，给出情绪标签。

## 可选标签
happy, sad, angry, fear, surprise, disgust

## 原则
1. 拿不准就保持 neutral，宁可漏标也不要乱标。
2. 旁白叙述大多数是 neutral；只有明显的吼、骂、哭、笑、惊叫才改。
3. 依据是语境：辱骂/挑衅/威胁→angry；惊叫/意外→surprise；哭腔/悲痛→sad；欢呼/打趣→happy；发抖/惧怕→fear；嫌恶/冷笑→disgust。
4. 不要因为句末有「！」就一律标情绪，反问句也常常是平静的。
5. 不要改文字，不要新增或删除行。

## 待判断（含上下各 2 行）
{items}

## 输出
[{{"id": 12, "emotion": "angry"}}]
"""


def _build_items(lines: Sequence[Dict[str, str]], indices: Sequence[int], context: int = 2) -> str:
    blocks = []
    for idx in indices:
        start = max(0, idx - context)
        end = min(len(lines), idx + context + 1)
        ctx = []
        for j in range(start, end):
            mark = ">>" if j == idx else "  "
            ctx.append(f"{mark} {j} [{lines[j]['character']}] ({lines[j].get('emotion') or 'neutral'}) {lines[j]['text']}")
        blocks.append("\n".join(ctx))
    return "\n\n".join(blocks)


def review_emotions(
    lines: List[Dict[str, str]],
    config=None,
    context: int = 2,
    batch_size: int = 15,
) -> Tuple[List[Dict[str, str]], List[Tuple[int, str, str]]]:
    """返回 (新行列表, [(行号, 原情绪, 新情绪)])。"""
    from modules.config_manager import get_config

    config = config or get_config()
    indices = [
        i for i, l in enumerate(lines)
        if (l.get("emotion") or "neutral") in ("neutral", "", "平静")
    ]
    if not indices:
        return lines, []

    from openai import OpenAI
    import httpx2

    client = OpenAI(
        base_url=config.llm_api.base_url,
        api_key=config.llm_api.api_key,
        http_client=httpx2.Client(trust_env=False, timeout=90),
    )
    allowed = {"happy", "sad", "angry", "fear", "surprise", "disgust"}
    changes: List[Tuple[int, str, str]] = []

    for start in range(0, len(indices), batch_size):
        batch = indices[start:start + batch_size]
        prompt = EMOTION_PROMPT.format(items=_build_items(lines, batch, context))
        response = client.chat.completions.create(
            model=config.llm_api.model,
            messages=[
                {"role": "system", "content": EMOTION_SYSTEM},
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
            emotion = str(item.get("emotion") or "").strip().lower()
            if idx in batch and emotion in allowed:
                old = lines[idx].get("emotion") or "neutral"
                if old != emotion:
                    lines[idx] = dict(lines[idx], emotion=emotion)
                    changes.append((idx, old, emotion))
    return lines, changes
