import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.cli import _parse_chapters, build_parser
from novelcast.pipeline import plan


def test_parse_chapters():
    assert _parse_chapters("1,3,5-7") == [1, 3, 5, 6, 7]
    assert _parse_chapters("2") == [2]


def test_plan_estimate():
    ch = SimpleNamespace(number=1, title="第一章", text="字" * 2820)
    row = plan([ch])[0]
    assert row["minutes"] == 10.0
    assert row["segments"] == 76


def test_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["run", "book.epub", "-n", "2", "--tts", "edge"])
    assert args.first_chapters == 2
    assert args.tts == "edge"
    assert args.command == "run"


if __name__ == "__main__":
    test_parse_chapters()
    test_plan_estimate()
    test_parser_defaults()
    print("cli tests passed")


def test_output_dir_from_config(tmp_path):
    from novelcast.config_manager import ConfigManager

    cfg = ConfigManager.__new__(ConfigManager)
    cfg.config = {"output_dir": str(tmp_path / "myout")}
    cfg.output_override = None
    path = cfg.get_output_dir("测试书")
    assert path == tmp_path / "myout" / "测试书_有声书"
    assert path.is_dir()


def test_output_override_wins(tmp_path):
    from novelcast.config_manager import ConfigManager

    cfg = ConfigManager.__new__(ConfigManager)
    cfg.config = {"output_dir": str(tmp_path / "myout")}
    cfg.output_override = tmp_path / "explicit"
    assert cfg.get_output_dir("测试书") == tmp_path / "explicit"
