"""
全书角色表（阶段 0）

逐块标注最大的问题是"只见树木不见森林"：同一角色在不同块里被写成
不同名字，或者同一句话被归给不同的人。这里先在全书范围抽一份角色
名录（名字 + 别名 + 性别/年龄），后面每个块的标注都以它为枚举约束。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from novelcast.log import log

ROSTER_VERSION = 1

# 单次送给 LLM 的最大字数（角色抽取只看人名，不需要太长上下文）
EXTRACT_CHUNK_CHARS = 6000
MAX_ALIASES = 8
PROMPT_MAP_MAX_CHARS = 3000

# 明显不是人名的词
JUNK_NAMES = {
    "他", "她", "它", "我", "你", "您", "我们", "你们", "他们", "她们", "它们",
    "这个", "那个", "这些", "那些", "自己", "别人", "大家", "众人", "有人",
    "旁白", "作者", "读者", "声音", "语气", "表情", "目光", "心里", "心中",
    # 动作/说话动词：LLM 偶尔会把「说」「笑道」当成说话人
    "说", "道", "问", "答", "喊", "叫", "笑", "哭", "叹", "哼", "想", "看",
    "听", "走", "来", "去", "站", "坐", "点头", "摇头", "开口", "回答",
    "追问", "自语", "低声", "大声", "轻声", "冷笑", "苦笑",
    "说道", "问道", "答道", "喊道", "叫道", "笑道", "哭道", "叹道", "骂道",
}

ROSTER_PROMPT = """你是小说角色分析助手。请阅读下面的小说片段，抽取其中出现的所有具名角色。

要求：
1. 只保留有名有姓或有固定称谓的角色，例如：林黛玉、老王、母亲、赵队长。
2. 不要输出代词（他/她/我/你/他们）、动作词（说/问/喊）、泛称（众人/有人/大家）。
3. aliases 写同一角色在本片段中的其他称呼（如"黛玉""林妹妹"），没有就留空数组。
4. gender 取 male / female / unknown；age 取 child / teen / adult / elder / unknown；
   role 取 protagonist / supporting / minor。
5. 同名但明显是两个人时，在 name 后加身份区分，如"张三(掌柜)"。
6. 只输出 JSON 数组，不要任何解释：

[{{"name":"角色名","aliases":["别名"],"gender":"female","age":"teen","role":"protagonist","description":"一句话说明"}}]

## 小说片段：
{text}"""


# ---------------------------------------------------------------- 工具函数

def _clean_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.strip().strip("「」『』\"'“”‘’《》[]【】()（）")
    name = re.sub(r"\s+", "", name)
    return name[:20]


def _norm(name: str) -> str:
    return re.sub(r"[\s·・,，。.、:：;；!！?？\"'“”‘’「」『』《》()（）\[\]【】]", "", name).lower()


def is_valid_name(name: str) -> bool:
    if not name or len(name) > 20:
        return False
    if name in JUNK_NAMES:
        return False
    # 「调皮地」「笑着说」这类状语/动作短语不是人名
    if name.endswith(("地", "着", "了")) and len(name) >= 2:
        return False
    if re.fullmatch(r"[\d\W_]+", name):
        return False
    return True


def _new_entry(name: str, aliases: Optional[Iterable[str]] = None, **kwargs) -> dict:
    return {
        "name": name,
        "aliases": [a for a in (aliases or []) if a and a != name][:MAX_ALIASES],
        "gender": kwargs.get("gender", "unknown"),
        "age": kwargs.get("age", "unknown"),
        "role": kwargs.get("role", "minor"),
        "description": kwargs.get("description", ""),
        "appearances": kwargs.get("appearances", 1),
    }


def _find_existing(characters: Dict[str, dict], name: str, aliases: Iterable[str]) -> Optional[str]:
    """按规范名或别名找到已有角色，返回其规范名。"""
    targets = {_norm(name)} | {_norm(a) for a in aliases if a}
    for canonical, info in characters.items():
        if _norm(canonical) in targets:
            return canonical
        for alias in info.get("aliases", []):
            if _norm(alias) in targets:
                return canonical
    return None


def merge_entries(characters: Dict[str, dict], entries: List[dict]) -> int:
    """把一批抽取结果合并进角色表，返回新增角色数。"""
    added = 0
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        name = _clean_name(raw.get("name", ""))
        if not is_valid_name(name):
            continue

        aliases = [_clean_name(a) for a in raw.get("aliases", []) or []]
        aliases = [a for a in aliases if is_valid_name(a) and a != name]

        existing = _find_existing(characters, name, aliases)
        if existing:
            info = characters[existing]
            info["appearances"] = info.get("appearances", 1) + 1
            merged = list(info.get("aliases", []))
            for alias in aliases:
                if alias not in merged and alias != existing:
                    merged.append(alias)
            info["aliases"] = merged[:MAX_ALIASES]
            # 补全空字段，保留更长的描述
            for key in ("gender", "age", "role"):
                value = raw.get(key)
                if value and info.get(key, "unknown") in ("", "unknown"):
                    info[key] = value
            desc = (raw.get("description") or "").strip()
            if len(desc) > len(info.get("description", "")):
                info["description"] = desc
        else:
            characters[name] = _new_entry(
                name,
                aliases,
                gender=raw.get("gender", "unknown"),
                age=raw.get("age", "unknown"),
                role=raw.get("role", "minor"),
                description=(raw.get("description") or "").strip(),
            )
            added += 1
    return added


def sort_roster(characters: Dict[str, dict]) -> Dict[str, dict]:
    role_rank = {"protagonist": 0, "supporting": 1, "minor": 2}
    ordered = sorted(
        characters.items(),
        key=lambda kv: (
            role_rank.get(kv[1].get("role", "minor"), 2),
            -int(kv[1].get("appearances", 1)),
            kv[0],
        ),
    )
    return dict(ordered)


# ---------------------------------------------------------------- 抽取

def _iter_chunks(chapters, max_chars: int = EXTRACT_CHUNK_CHARS):
    """按段落把章节拼成 <= max_chars 的片段，尽量不截断段落。"""
    for chapter in chapters:
        paragraphs = [p for p in chapter.text.split("\n") if p.strip()]
        buffer: List[str] = []
        size = 0
        for para in paragraphs:
            if size + len(para) > max_chars and buffer:
                yield chapter.title, "\n".join(buffer)
                buffer, size = [], 0
            if len(para) > max_chars:
                # 单段超长，硬切
                for i in range(0, len(para), max_chars):
                    yield chapter.title, para[i:i + max_chars]
                continue
            buffer.append(para)
            size += len(para) + 1
        if buffer:
            yield chapter.title, "\n".join(buffer)


def _parse_roster_response(raw: str) -> List[dict]:
    if not raw:
        return []
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("characters", [])
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


async def _extract_chunk_async(client, model: str, text: str, retries: int = 2) -> List[dict]:
    prompt = ROSTER_PROMPT.replace("{text}", text)
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是一个JSON输出助手，只输出JSON数组。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                ),
                timeout=120,
            )
            return _parse_roster_response(response.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - 网络/解析都可能失败，统一重试
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(2 * (attempt + 1))
    log.info(f"    ⚠️ 角色抽取失败（{type(last_error).__name__}: {last_error}），跳过该片段")
    return []


async def build_roster_async(chapters, book_name: str, client, config, max_chars: int = EXTRACT_CHUNK_CHARS) -> dict:
    """全书角色抽取（分片并发 + 合并）。"""
    chunks = list(_iter_chunks(chapters, max_chars))
    log.info(f"  🔍 角色抽取: 全书 {sum(len(c.text) for c in chapters)} 字 → {len(chunks)} 个片段")

    semaphore = asyncio.Semaphore(max(1, config.concurrency.llm_concurrency))
    model = config.llm_api.model

    async def work(idx: int, title: str, text: str) -> List[dict]:
        async with semaphore:
            start = time.time()
            entries = await _extract_chunk_async(client, model, text)
            log.info(f"    片段{idx+1}/{len(chunks)} ({len(text)}字): {len(entries)}个角色，{time.time()-start:.1f}s")
            return entries

    results = await asyncio.gather(*(work(i, t, x) for i, (t, x) in enumerate(chunks)))

    characters: Dict[str, dict] = {}
    for entries in results:
        merge_entries(characters, entries)

    roster = {
        "version": ROSTER_VERSION,
        "book": book_name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "characters": sort_roster(characters),
    }
    log.info(f"  🎭 角色表: 共 {len(roster['characters'])} 个角色")
    return roster


# ---------------------------------------------------------------- 读写

def save_roster(roster: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(roster, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_roster(path: Path) -> Optional[dict]:
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or "characters" not in data:
        return None
    return data


def roster_to_prompt_map(roster: dict, max_chars: int = PROMPT_MAP_MAX_CHARS) -> str:
    """把角色表压成提示词里的一段文本（名字 + 别名 + 性别年龄）。"""
    characters = (roster or {}).get("characters", {})
    if not characters:
        return "（暂无已知角色）"

    gender_cn = {"male": "男", "female": "女", "unknown": ""}
    age_cn = {"child": "儿童", "teen": "少年", "adult": "成年", "elder": "老年", "unknown": ""}

    lines = []
    for name, info in characters.items():
        parts = [name]
        aliases = [a for a in info.get("aliases", []) if a]
        if aliases:
            parts.append("别名：" + "、".join(aliases[:5]))
        tags = [gender_cn.get(info.get("gender", "unknown"), ""), age_cn.get(info.get("age", "unknown"), "")]
        tags = [t for t in tags if t]
        if tags:
            parts.append("/".join(tags))
        if info.get("role") == "protagonist":
            parts.append("主角")
        lines.append("- " + "（".join([parts[0], "；".join(parts[1:])]) + "）" if len(parts) > 1 else "- " + parts[0])

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n- …（其余角色略）"
    return text
