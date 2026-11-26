"""
LLM 分块结果缓存

同一段文本 + 同一模型 + 同一提示词 + 同一角色表，标注结果应当一致。
把结果按 sha1 落盘，既能避免重复烧钱，也让中断后重跑可以续上。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _safe(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip()[:80] or "book"


class LlmCache:
    """按 (模型, 提示词版本, 角色表, 文本) 的 sha1 缓存标注结果。"""

    def __init__(
        self,
        book_name: str,
        model: str,
        prompt_version: str,
        root: Optional[Path] = None,
        base_url: str = "",
    ):
        self.dir = Path(root or (PROJECT_ROOT / "llm_cache")) / _safe(book_name)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.prompt_version = prompt_version
        self.base_url = base_url
        self.hits = 0
        self.misses = 0

    def _key(self, text: str, context: str = "") -> str:
        h = hashlib.sha1()
        for part in (self.base_url, self.model, self.prompt_version, context, text):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def _path(self, text: str, context: str = "") -> Path:
        key = self._key(text, context)
        return self.dir / key[:2] / f"{key}.json"

    def get(self, text: str, context: str = "") -> Optional[List[dict]]:
        path = self._path(text, context)
        if not path.exists():
            self.misses += 1
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.misses += 1
            return None
        lines = data.get("lines")
        if not isinstance(lines, list):
            self.misses += 1
            return None
        self.hits += 1
        return lines

    def put(self, text: str, lines: List[dict], context: str = "") -> None:
        path = self._path(text, context)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "chars": len(text),
            "lines": lines,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def clear(self) -> int:
        """删除本书全部缓存，返回删除的文件数。"""
        removed = 0
        for path in self.dir.rglob("*.json"):
            path.unlink()
            removed += 1
        return removed

    @property
    def stats(self) -> Dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
