import pathlib

root = pathlib.Path(r"D:\code\NovelCast")
targets = []
for pattern in ("novelcast/*.py", "scripts/*.py", "tests/*.py", "tools/dev/*.py"):
    targets.extend(root.glob(pattern))

changed = 0
for p in targets:
    s = p.read_text(encoding="utf-8")
    t = (s.replace("from novelcast.", "from novelcast.")
           .replace("import novelcast.", "import novelcast.")
           .replace("from novelcast import", "from novelcast import"))
    if t != s:
        p.write_text(t, encoding="utf-8")
        changed += 1
        print("updated", p.relative_to(root))
print("changed files:", changed)
