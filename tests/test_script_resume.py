import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.novel_reader import Chapter
from scripts.generate import _filter_chapters_content, _load_script_result


class FakeConfig:
    def __init__(self, root):
        self.root = Path(root)

    def get_output_dir(self, book_name):
        return self.root


def _write_script(root, chapter, texts, partial=False):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{chapter.number:03d}_{chapter.title}_script.json").write_text(
        json.dumps(
            {
                "chapter": {"number": chapter.number, "title": chapter.title},
                "coverage": 1.0,
                "partial": partial,
                "lines": [
                    {"character": "旁白", "text": t, "emotion": "neutral", "voice": ""}
                    for t in texts
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_partial_script_rejected(tmp_path):
    chapter = Chapter(number=1, title="第一章", text="甲" * 500)
    _write_script(tmp_path, chapter, ["甲" * 50])
    assert _load_script_result(chapter, "书", FakeConfig(tmp_path)) is None


def test_partial_flag_rejected(tmp_path):
    chapter = Chapter(number=1, title="第一章", text="甲" * 50)
    _write_script(tmp_path, chapter, ["甲" * 50], partial=True)
    assert _load_script_result(chapter, "书", FakeConfig(tmp_path)) is None


def test_full_script_loaded(tmp_path):
    chapter = Chapter(number=1, title="第一章", text="甲" * 500)
    _write_script(tmp_path, chapter, ["甲" * 500])
    result = _load_script_result(chapter, "书", FakeConfig(tmp_path))
    assert result is not None and len(result.lines) == 1


def test_filter_marks_partial():
    chapter = Chapter(number=1, title="第一章", text="乙" * 100)
    out = _filter_chapters_content([chapter], first_chars=40)
    assert out[0].partial is True
    full = _filter_chapters_content([Chapter(number=2, title="第二章", text="丙" * 10)], first_chars=40)
    assert full[0].partial is False


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_partial_script_rejected(Path(d) / "a")
    with tempfile.TemporaryDirectory() as d:
        test_partial_flag_rejected(Path(d) / "b")
    with tempfile.TemporaryDirectory() as d:
        test_full_script_loaded(Path(d) / "c")
    test_filter_marks_partial()
    print("resume tests passed")
