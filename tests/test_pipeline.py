# -*- coding: utf-8 -*-
"""pipeline 编排测试：plan 估算、离线续跑、TTS 阶段与 fresh 清理，全部不触网。"""

import asyncio
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import engine
from novelcast.dialogue_splitter import DialogueLine
from novelcast.engine import ChapterSplitResult, _save_script_result
from novelcast.novel_reader import Chapter
from novelcast.pipeline import plan, run_book


class Cfg:
    def __init__(self, root):
        self.root = Path(root)
        self.config = {
            "output_dir": str(self.root),
            "roster_mode": "full",
            "tts": {"provider": "edge"},
            "voice_presets": {"default": "冰糖"},
        }

    def get_output_dir(self, book_name):
        path = self.root / f"{book_name}_有声书"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _success(chapter, lines=None):
    if lines is None:
        lines = [DialogueLine(character="旁白", text=chapter.text, emotion="neutral")]
    return ChapterSplitResult(chapter=chapter, lines=lines, coverage=1.0, success=True)


def _fail_chapter(chapter):
    return ChapterSplitResult(chapter=chapter, lines=[], coverage=0.0, success=False, error="失败")


def test_plan_estimates_chars_segments_and_minutes():
    chapters = [
        Chapter(number=1, title="长章", text="字" * 1000),
        Chapter(number=2, title="空章", text=""),
    ]
    rows = plan(chapters)

    assert [r["number"] for r in rows] == [1, 2]
    assert rows[0]["title"] == "长章"
    assert rows[0]["chars"] == 1000
    assert rows[0]["segments"] == 27  # round(1000 / 37)
    assert rows[0]["minutes"] == 3.5
    assert rows[1]["chars"] == 0
    assert rows[1]["segments"] == 1  # 至少 1 段
    assert rows[1]["minutes"] == 0.0
    assert plan([]) == []


def test_plan_honours_custom_and_zero_rate():
    chapters = [Chapter(number=1, title="短章", text="字" * 50)]
    assert plan(chapters, chars_per_minute=100)[0]["minutes"] == 0.5
    assert plan(chapters, chars_per_minute=0)[0]["minutes"] == 0


def test_run_book_offline_reuses_scripts_without_tts(tmp_path, monkeypatch):
    config = Cfg(tmp_path)
    chapter = Chapter(number=1, title="第一章", text="你好世界。" * 5)
    _save_script_result(_success(chapter), "离线书", config)

    async def no_tts(*args, **kwargs):
        raise AssertionError("offline 模式不应调用 TTS")

    monkeypatch.setattr(engine, "generate_all_audio", no_tts)

    result = asyncio.run(run_book([chapter], "离线书", config, offline=True, split_only=True))

    assert result["audios"] == []
    assert result["chapters"] == 1
    book_dir = Path(result["output_dir"])
    assert (book_dir / "characters.json").exists()
    assert (book_dir / "cast.json").exists()
    assert (book_dir / "001_第一章_script.json").exists()


def test_run_book_offline_without_scripts_returns_zero(tmp_path, monkeypatch):
    config = Cfg(tmp_path)
    chapter = Chapter(number=1, title="缺剧本", text="没有剧本的正文。")

    async def no_tts(*args, **kwargs):
        raise AssertionError("没有成功章节时不应调用 TTS")

    monkeypatch.setattr(engine, "generate_all_audio", no_tts)

    result = asyncio.run(run_book([chapter], "离线书", config, offline=True))

    assert result["chapters"] == 0
    assert result["audios"] == []
    book_dir = Path(result["output_dir"])
    assert (book_dir / "characters.json").exists()
    assert not list(book_dir.glob("*_script.json"))


def test_run_book_tts_path_uses_split_and_generate(tmp_path, monkeypatch):
    config = Cfg(tmp_path)
    config.config["roster_mode"] = "off"
    chapter = Chapter(number=1, title="标题", text="你好世界。")
    captured = {}

    async def fake_split(chapters, book_name, config, **kwargs):
        captured["split_kwargs"] = kwargs
        return [_success(chapter)], []

    async def fake_generate(results, book_name, config, cast, **kwargs):
        captured["results"] = results
        captured["generate_kwargs"] = kwargs
        return [str(tmp_path / "001_标题.wav")]

    monkeypatch.setattr(engine, "split_all_chapters", fake_split)
    monkeypatch.setattr(engine, "generate_all_audio", fake_generate)

    result = asyncio.run(run_book([chapter], "书", config))

    assert result["chapters"] == 1
    assert result["audios"] == [str(tmp_path / "001_标题.wav")]
    assert result["m4b"] is None
    assert captured["split_kwargs"]["offline"] is False
    assert captured["split_kwargs"]["resume"] is True
    assert captured["generate_kwargs"]["skip_existing"] is True
    assert captured["generate_kwargs"]["restart"] is False


def test_run_book_exports_m4b_when_requested(tmp_path, monkeypatch):
    config = Cfg(tmp_path)
    config.config["roster_mode"] = "off"
    config.config["author"] = "作者"
    chapter = Chapter(number=1, title="章节", text="你好。")
    audio = str(tmp_path / "001_章节.wav")
    m4b_calls = {}

    async def fake_split(chapters, book_name, config, **kwargs):
        return [_success(chapter)], []

    async def fake_generate(results, book_name, config, cast, **kwargs):
        return [audio]

    module = ModuleType("novelcast.m4b")

    def fake_build(audios, titles, path, title=None, artist=None):
        m4b_calls.update({"audios": audios, "titles": titles, "path": path, "title": title, "artist": artist})
        Path(path).write_bytes(b"m4b")
        return str(path)

    module.build_m4b = fake_build
    monkeypatch.setitem(sys.modules, "novelcast.m4b", module)
    monkeypatch.setattr(engine, "split_all_chapters", fake_split)
    monkeypatch.setattr(engine, "generate_all_audio", fake_generate)

    result = asyncio.run(run_book([chapter], "书", config, audio_format="m4b"))

    assert result["m4b"] == str(Path(result["output_dir"]) / "书.m4b")
    assert m4b_calls["audios"] == [audio]
    assert m4b_calls["titles"] == ["章节"]
    assert m4b_calls["title"] == "书"
    assert m4b_calls["artist"] == "作者"
    assert Path(m4b_calls["path"]).exists()


def test_run_book_fresh_clears_previous_output(tmp_path, monkeypatch):
    config = Cfg(tmp_path)
    config.config["roster_mode"] = "off"
    out = tmp_path / "手工输出"
    out.mkdir()
    stale = out / "stale.txt"
    stale.write_text("old", encoding="utf-8")
    chapter = Chapter(number=1, title="失败章", text="正文。")

    async def fake_split(chapters, book_name, config, **kwargs):
        return [], [_fail_chapter(chapter)]

    async def no_tts(*args, **kwargs):
        raise AssertionError("不应调用 TTS")

    monkeypatch.setattr(engine, "split_all_chapters", fake_split)
    monkeypatch.setattr(engine, "generate_all_audio", no_tts)

    result = asyncio.run(run_book([chapter], "书", config, output_dir=out, fresh=True))

    assert result["chapters"] == 0
    assert out.exists()
    assert not stale.exists()
