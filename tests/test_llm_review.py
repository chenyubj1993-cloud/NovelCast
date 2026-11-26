"""unit tests for novelcast.llm_review (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from novelcast import llm_review


def _cfg():
    return SimpleNamespace(
        llm_api=SimpleNamespace(
            base_url="http://127.0.0.1:1", api_key="test", model="fake-model"
        ),
        config={},
    )


class _FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        content = self.replies.pop(0)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _FakeClient:
    def __init__(self, replies):
        self.chat = SimpleNamespace(completions=_FakeCompletions(replies))


def _install(monkeypatch, replies):
    fake = _FakeClient(replies)
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: fake)
    return fake


def test_no_unknown_returns_unchanged(monkeypatch):
    lines = [{"character": "叶秋", "text": "来了。"}]
    out, changes = llm_review.review_unknown(lines, {"叶秋": {}}, _cfg())
    assert out == lines
    assert changes == []


def test_applies_change_by_id(monkeypatch):
    lines = [
        {"character": "旁白", "text": "他推门进来。"},
        {"character": "未知", "text": "你来了。"},
    ]
    fake = _install(monkeypatch, ['[{"id": 1, "speaker": "叶秋"}]'])
    out, changes = llm_review.review_unknown(lines, {"叶秋": {"gender": "male"}}, _cfg())
    assert changes == [(1, "未知", "叶秋")]
    assert out[1]["character"] == "叶秋"
    assert fake.chat.completions.calls == 1


def test_bad_json_and_unknown_id_are_ignored(monkeypatch):
    lines = [{"character": "未知", "text": "嗯。"}]
    _install(monkeypatch, ["这不是 JSON"])
    out, changes = llm_review.review_unknown(lines, {}, _cfg())
    assert changes == []
    assert out[0]["character"] == "未知"

    lines2 = [{"character": "未知", "text": "嗯。"}]
    _install(monkeypatch, ['[{"id": 99, "speaker": "叶秋"}]'])
    out2, changes2 = llm_review.review_unknown(lines2, {}, _cfg())
    assert changes2 == []


def test_batches_split_by_size(monkeypatch):
    lines = [{"character": "未知", "text": f"第{i}句。"} for i in range(3)]
    fake = _install(monkeypatch, ["[]", "[]", "[]"])
    llm_review.review_unknown(lines, {}, _cfg(), batch_size=1)
    assert fake.chat.completions.calls == 3


@pytest.mark.parametrize("context", [0, 2])
def test_context_window_does_not_crash(monkeypatch, context):
    lines = [
        {"character": "旁白", "text": "甲。"},
        {"character": "未知", "text": "乙。"},
        {"character": "旁白", "text": "丙。"},
    ]
    _install(monkeypatch, ["[]"])
    out, changes = llm_review.review_unknown(lines, {}, _cfg(), context=context)
    assert changes == []
