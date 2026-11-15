"""把 novelcast/*.py 与 scripts/generate.py 里的 print( 批量换成 log.info(。

只做机械替换，不做语义判断；替换后由 py_compile + pytest 兜底。
"""
import ast
import pathlib

IMPORT = "from novelcast.log import log\n"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def insert_import(source: str) -> str:
    tree = ast.parse(source)
    line = 0
    if tree.body:
        first = tree.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            line = first.end_lineno or 0
    lines = source.splitlines(keepends=True)
    lines.insert(line, IMPORT)
    return "".join(lines)


def main() -> None:
    files = sorted((ROOT / "novelcast").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
    changed = 0
    for path in files:
        if path.name == "log.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "print(" not in source:
            continue
        count = source.count("print(")
        source = source.replace("print(", "log.info(")
        if IMPORT.strip() not in source:
            source = insert_import(source)
        path.write_text(source, encoding="utf-8")
        changed += 1
        print(f"{path.relative_to(ROOT)}: {count} 处")
    print(f"共处理 {changed} 个文件")


if __name__ == "__main__":
    main()
