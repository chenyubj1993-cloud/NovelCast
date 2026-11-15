"""修正 import 位置（第二版）：放到所有 __future__ 导入之后。"""
import ast
import pathlib

IMPORT = "from novelcast.log import log"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def main() -> None:
    files = sorted((ROOT / "novelcast").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
    for path in files:
        source = path.read_text(encoding="utf-8")
        if IMPORT not in source:
            continue
        lines = [ln for ln in source.splitlines(keepends=True) if ln.strip() != IMPORT]
        text = "".join(lines)
        idx = None
        for i, ln in enumerate(lines):
            if ln.startswith("from __future__"):
                idx = i
                break
        if idx is not None:
            j = idx
            while j < len(lines) and lines[j].startswith("from __future__"):
                j += 1
            lines.insert(j, IMPORT + "\n")
        else:
            tree = ast.parse(text)
            line = 0
            if tree.body:
                first = tree.body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    line = first.end_lineno or 0
            while line < len(lines) and (not lines[line].strip() or lines[line].startswith("#")):
                line += 1
            lines.insert(line, IMPORT + "\n")
        path.write_text("".join(lines), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
