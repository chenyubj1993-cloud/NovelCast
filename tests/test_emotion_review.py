# -*- coding: utf-8 -*-
"""emotion_review 测试：只改 neutral、批量解析、非法结果与解析失败容错。"""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.emotion_review import EMOTION_SYSTEM, _build_items, review_emotions


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content = self.responses.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _install_fake_llm(monkeypatch, responses):
    completions = FakeCompletions(responses)
    http_module = ModuleType("httpx2")
    http_module.Client = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "httpx2", http_module)

    class FakeOpenAI:
        last = None

        def __init__(self, **kwargs):
            FakeOpenAI.last = self
            self.init_kwargs = kwargs
            self.chat = SimpleNamespace(completions=completions)

    openai_module = ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    return completions, FakeOpenAI


def _config():
    return SimpleNamespace(
        llm_api=SimpleNamespace(base_url="https://api.example.com/v1", api_key="test-key", model="test-model")
    )


def test_review_emotions_only_changes_neutral_lines(monkeypatch):
    lines = [
        {"character": "旁白", "text": "他笑了。", "emotion": "happy"},
        {"character": "甲", "text": "滚出去！", "emotion": "neutral"},
        {"character": "乙", "text": "今天天气不错。", "emotion": ""},
        {"character": "丙", "text": "我好难过。", "emotion": "sad"},
        {"character": "丁", "text": "什么？！"},  # 缺 emotion 视为 neutral
    ]
    completions, fake_openai = _install_fake_llm(
        monkeypatch,
        ['[{"id": 1, "emotion": "angry"}, {"id": 4, "emotion": "surprise"}, {"id": 3, "emotion": "fear"}]'],
    )

    updated, changes = review_emotions(lines, _config(), context=1, batch_size=15)

    assert updated[0]["emotion"] == "happy"
    assert updated[1]["emotion"] == "angry"
    assert updated[2]["emotion"] == ""
    assert updated[3]["emotion"] == "sad"
    assert updated[4]["emotion"] == "surprise"
    assert changes == [(1, "neutral", "angry"), (4, "neutral", "surprise")]
    assert len(completions.requests) == 1
    sent = completions.requests[0]
    assert sent["model"] == "test-model"
    assert sent["temperature"] == 0
    assert sent["messages"][0]["content"] == EMOTION_SYSTEM
    assert fake_openai.last.init_kwargs["base_url"] == "https://api.example.com/v1"
    assert fake_openai.last.init_kwargs["api_key"] == "test-key"


def test_review_emotions_sends_batches_with_context(monkeypatch):
    lines = [
        {"character": "甲", "text": "第一行", "emotion": "neutral"},
        {"character": "乙", "text": "第二行", "emotion": "neutral"},
        {"character": "丙", "text": "第三行", "emotion": "neutral"},
    ]
    completions, _ = _install_fake_llm(
        monkeypatch,
        ['[{"id": 0, "emotion": "happy"}]', '[{"id": 2, "emotion": "sad"}]'],
    )

    _, changes = review_emotions(lines, _config(), context=0, batch_size=2)

    assert changes == [(0, "neutral", "happy"), (2, "neutral", "sad")]
    assert len(completions.requests) == 2
    first_prompt = completions.requests[0]["messages"][1]["content"]
    second_prompt = completions.requests[1]["messages"][1]["content"]
    assert ">> 0" in first_prompt and ">> 1" in first_prompt
    assert ">> 2" not in first_prompt
    assert ">> 2" in second_prompt


def test_invalid_ids_and_emotions_are_ignored(monkeypatch):
    lines = [
        {"character": "甲", "text": "一", "emotion": "neutral"},
        {"character": "乙", "text": "二", "emotion": "neutral"},
        {"character": "丙", "text": "三", "emotion": "neutral"},
    ]
    completions, _ = _install_fake_llm(
        monkeypatch,
        [
            '[{"id": "x", "emotion": "happy"}, {"id": 99, "emotion": "sad"}, '
            '{"id": 0, "emotion": "neutral"}, {"id": 1, "emotion": "HAPPY"}, '
            '{"id": 2, "emotion": "weird"}]'
        ],
    )

    updated, changes = review_emotions(lines, _config(), context=0, batch_size=10)

    assert changes == [(1, "neutral", "happy")]
    assert updated[0]["emotion"] == "neutral"
    assert updated[1]["emotion"] == "happy"
    assert updated[2]["emotion"] == "neutral"
    assert len(completions.requests) == 1


def test_malformed_llm_responses_are_tolerated(monkeypatch):
    lines = [
        {"character": "甲", "text": "一", "emotion": "neutral"},
        {"character": "乙", "text": "二", "emotion": "neutral"},
    ]
    completions, _ = _install_fake_llm(
        monkeypatch,
        ["抱歉，我无法判断这些行。", '{"broken": ['],
    )

    updated, changes = review_emotions(lines, _config(), context=0, batch_size=1)

    assert changes == []
    assert [line["emotion"] for line in updated] == ["neutral", "neutral"]
    assert len(completions.requests) == 2


def test_no_neutral_lines_does_not_create_client(monkeypatch):
    lines = [
        {"character": "甲", "text": "一", "emotion": "happy"},
        {"character": "乙", "text": "二", "emotion": "sad"},
        {"character": "丙", "text": "三", "emotion": "angry"},
    ]
    completions, fake_openai = _install_fake_llm(monkeypatch, [])

    updated, changes = review_emotions(lines, _config())

    assert changes == []
    assert updated == lines
    assert fake_openai.last is None
    assert completions.requests == []


def test_build_items_marks_target_and_includes_context():
    lines = [
        {"character": "甲", "text": "零", "emotion": "neutral"},
        {"character": "乙", "text": "一", "emotion": "sad"},
        {"character": "丙", "text": "二", "emotion": ""},
        {"character": "丁", "text": "三", "emotion": "happy"},
        {"character": "戊", "text": "四", "emotion": "neutral"},
    ]

    text = _build_items(lines, [2], context=1)

    assert ">> 2 [丙] (neutral) 二" in text
    assert "  1 [乙] (sad) 一" in text
    assert "  3 [丁] (happy) 三" in text
    assert "0 [甲]" not in text
    assert "4 [戊]" not in text
