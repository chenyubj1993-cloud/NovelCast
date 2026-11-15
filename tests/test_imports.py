# -*- coding: utf-8 -*-
"""导入冒烟测试：用 stub 顶替 openai，确认所有模块能正常加载。"""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if "openai" not in sys.modules:
    stub = types.ModuleType("openai")

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.OpenAI = _Client
    stub.AsyncOpenAI = _Client
    sys.modules["openai"] = stub

MODULES = [
    "config_manager", "novel_reader", "character_registry", "cast_manager",
    "llm_cache", "dialogue_splitter", "voice_assigner", "tts_generator",
    "audio_processor", "coverage_analyzer", "utils",
]


def test_modules_import():
    for name in MODULES:
        __import__(f"novelcast.{name}")


def test_generate_script_imports():
    spec = importlib.util.spec_from_file_location("novelcast_generate", ROOT / "scripts" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main") and hasattr(mod, "split_all_chapters")
    assert hasattr(mod, "_load_script_result")
    print("  scripts/generate.py 导入成功")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
