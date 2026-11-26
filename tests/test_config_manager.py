# -*- coding: utf-8 -*-
"""config_manager 单元测试：默认值合并、深拷贝隔离、输出目录优先级与 TTS 字段过滤。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import config_manager as cfg_mod
from novelcast.config_manager import ConfigManager


def _write_config(tmp_path, data, name="settings.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _new_manager(tmp_path, name="settings.json", user_config=None):
    """user_config 为 None 时使用不存在的路径，走「首次运行保存默认配置」分支。"""
    if user_config is None:
        path = tmp_path / name
    else:
        path = _write_config(tmp_path, user_config, name)
    return ConfigManager(config_path=str(path))


# ============================================================
# 默认值 / 深拷贝
# ============================================================

def test_user_config_is_deep_merged_with_defaults(tmp_path):
    manager = _new_manager(tmp_path, user_config={
        "generation": {"chunk_size": 4321},
        "tts": {"max_chars": 88},
    })

    # 用户值覆盖默认值
    assert manager.config["generation"]["chunk_size"] == 4321
    assert manager.generation.chunk_size == 4321
    assert manager.tts.max_chars == 88

    # 同级的其它默认值仍在
    assert manager.config["generation"]["max_duration_per_file"] == 900
    assert manager.config["tts"]["sample_rate"] == 24000
    assert manager.llm_api.model == "deepseek-chat"


def test_configs_do_not_leak_between_instances_or_defaults(tmp_path):
    first = _new_manager(tmp_path, name="first.json")
    second = _new_manager(tmp_path, name="second.json")

    assert first.config["tts"] is not cfg_mod.DEFAULT_CONFIG["tts"]

    first.config["tts"]["provider"] = "被篡改"
    first.config["generation"]["chunk_size"] = -1

    assert cfg_mod.DEFAULT_CONFIG["tts"]["provider"] == "edge"
    assert cfg_mod.DEFAULT_CONFIG["generation"]["chunk_size"] == 1500
    assert second.config["tts"]["provider"] == "edge"
    assert second.config["generation"]["chunk_size"] == 1500


def test_invalid_config_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ 这不是合法 JSON", encoding="utf-8")

    manager = ConfigManager(config_path=str(path))

    assert manager.config["tts"]["provider"] == "edge"
    assert manager.config["output_dir"] == "output"


# ============================================================
# 输出目录优先级
# ============================================================

def test_output_dir_default_uses_project_root(tmp_path, monkeypatch):
    project = tmp_path / "project"
    monkeypatch.setattr(cfg_mod, "PROJECT_ROOT", project)
    manager = _new_manager(tmp_path)

    assert manager.config["output_dir"] == "output"
    assert manager.get_output_dir("书") == project / "output" / "书_有声书"


def test_output_dir_config_and_override_precedence(tmp_path, monkeypatch):
    project = tmp_path / "project"
    monkeypatch.setattr(cfg_mod, "PROJECT_ROOT", project)
    manager = _new_manager(tmp_path)

    manager.config["output_dir"] = "books"
    configured = manager.get_output_dir("我的书")
    assert configured == project / "books" / "我的书_有声书"
    assert configured.is_dir()

    # --output 生效后不再拼「书名_有声书」，且优先于 config 里的 output_dir
    manager.output_override = tmp_path / "explicit"
    explicit = manager.get_output_dir("我的书")
    assert explicit == tmp_path / "explicit"
    assert explicit.is_dir()
    assert "我的书_有声书" not in explicit.name


def test_output_dir_relative_override_uses_project_root(tmp_path, monkeypatch):
    project = tmp_path / "project"
    monkeypatch.setattr(cfg_mod, "PROJECT_ROOT", project)
    manager = _new_manager(tmp_path)

    manager.output_override = "相对输出"

    assert manager.get_output_dir("书") == project / "相对输出"


def test_output_dir_expands_user_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    manager = _new_manager(tmp_path)

    manager.config["output_dir"] = "~/audiobooks"

    assert manager.get_output_dir("书") == home / "audiobooks" / "书_有声书"


# ============================================================
# TtsConfig / get / set / save
# ============================================================

def test_tts_config_filters_unknown_keys(tmp_path):
    manager = _new_manager(tmp_path, user_config={
        "tts": {"provider": "edge", "unknown_option": 123},
    })

    assert manager.tts.provider == "edge"
    assert not hasattr(manager.tts, "unknown_option")
    # 原始 dict 仍保留用户配置，只是不会被塞进 dataclass
    assert manager.config["tts"]["unknown_option"] == 123


def test_get_set_and_apply_tts_overrides(tmp_path):
    manager = _new_manager(tmp_path)

    assert manager.get("tts.max_chars") == 300
    assert manager.get("tts.missing", 7) == 7

    manager.set("tts.max_chars", 111)
    assert manager.config["tts"]["max_chars"] == 111

    manager.config["tts"]["provider"] = "indextts2"
    manager.apply_tts_overrides(provider=None, max_chars=222, emotion_mode="vector")

    # None 表示命令行没传，不应覆盖已有值
    assert manager.config["tts"]["provider"] == "indextts2"
    assert manager.config["tts"]["max_chars"] == 222
    assert manager.tts.max_chars == 222
    assert manager.tts.emotion_mode == "vector"


def test_save_config_roundtrip(tmp_path):
    path = tmp_path / "saved.json"
    manager = ConfigManager(config_path=str(path))
    manager.set("generation.chunk_size", 777)
    manager.save_config()

    reloaded = ConfigManager(config_path=str(path))

    assert reloaded.generation.chunk_size == 777
