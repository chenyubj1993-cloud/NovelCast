"""单元测试：LLM 分块结果缓存（novelcast.llm_cache.LlmCache）。"""

from __future__ import annotations

import json

from novelcast.llm_cache import LlmCache

LINES = [
    {"character": "旁白", "text": "他推门而入。", "emotion": "neutral"},
    {"character": "叶修", "text": "来了。", "emotion": "calm"},
]


def make_cache(tmp_path, **kwargs) -> LlmCache:
    params = {
        "book_name": "测试书",
        "model": "deepseek-chat",
        "prompt_version": "v3",
        "root": tmp_path,
    }
    params.update(kwargs)
    return LlmCache(**params)


def test_put_get_roundtrip_and_stats(tmp_path):
    cache = make_cache(tmp_path)
    assert cache.get("第一段正文") is None
    cache.put("第一段正文", LINES)
    assert cache.get("第一段正文") == LINES
    assert cache.stats == {"hits": 1, "misses": 1}

    # 落盘路径：root/书名/key 前两位/key.json
    path = cache._path("第一段正文")
    assert path.exists()
    assert path.parent.parent == tmp_path / "测试书"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["model"] == "deepseek-chat"
    assert payload["prompt_version"] == "v3"
    assert payload["chars"] == len("第一段正文")
    assert payload["lines"] == LINES


def test_key_changes_with_model_prompt_version_base_url_text_context(tmp_path):
    text = "同一段正文"
    cache = make_cache(tmp_path, model="model-a", prompt_version="v1", base_url="https://api.example")
    keys = {
        cache._key(text),
        make_cache(tmp_path, model="model-b", prompt_version="v1", base_url="https://api.example")._key(text),
        make_cache(tmp_path, model="model-a", prompt_version="v2", base_url="https://api.example")._key(text),
        make_cache(tmp_path, model="model-a", prompt_version="v1", base_url="https://other.example")._key(text),
        cache._key(text + "（改了一个字）"),
        cache._key(text, context="角色表A"),
    }
    assert len(keys) == 6

    # 行为层面：换了 context 就读不到旧结果
    cache.put(text, LINES, context="ctx-a")
    assert cache.get(text, context="ctx-b") is None
    assert cache.get(text, context="ctx-a") == LINES


def test_book_name_is_sanitized_into_a_single_directory(tmp_path):
    cache = make_cache(tmp_path, book_name="第1章 他/她: 说?")
    assert cache.dir.parent == tmp_path
    assert not set(cache.dir.name) & set('<>:"/\\|?*')
    assert cache.dir.is_dir()


def test_clear_removes_every_entry_of_the_book(tmp_path):
    cache = make_cache(tmp_path)
    cache.put("一", LINES)
    cache.put("二", LINES)
    cache.put("一", LINES, context="ctx")
    assert cache.clear() == 3
    assert list((tmp_path / "测试书").rglob("*.json")) == []
    assert cache.get("一") is None


def test_corrupt_json_is_treated_as_miss(tmp_path):
    cache = make_cache(tmp_path)
    cache.put("正文", LINES)
    cache._path("正文").write_text("{not json at all", encoding="utf-8")

    assert cache.get("正文") is None
    assert cache.misses == 1
    assert cache.hits == 0


def test_payload_without_lines_is_treated_as_miss(tmp_path):
    cache = make_cache(tmp_path)
    path = cache._path("正文")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": cache.model}), encoding="utf-8")

    assert cache.get("正文") is None
    assert cache.misses == 1
