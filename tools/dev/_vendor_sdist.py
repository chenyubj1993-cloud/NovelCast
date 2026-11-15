# -*- coding: utf-8 -*-
"""从 PyPI sdist 安装无 wheel 的纯 Python 包到 .vendor。

用法: python _vendor_sdist.py randomname argbind ...
"""
import io
import json
import pathlib
import shutil
import sys
import tarfile
import urllib.request
import zipfile

VENDOR = pathlib.Path(__file__).resolve().parent / ".vendor"


def install(pkg):
    meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=30))
    src = None
    for u in meta["urls"]:
        if u["filename"].endswith(".tar.gz"):
            src = u
            break
    if src is None:
        print("no sdist", pkg)
        return False
    print("sdist", src["filename"], round(src["size"] / 1e6, 2), "MB")
    data = urllib.request.urlopen(src["url"], timeout=300).read()
    tmp = pathlib.Path(".tmp_sdist")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    tf = tarfile.open(fileobj=io.BytesIO(data))
    tf.extractall(tmp)
    root = [p for p in tmp.iterdir() if p.is_dir()][0]
    norm = pkg.replace("-", "_").lower()
    copied = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name in ("tests", "test", "docs", "doc", "examples", "build"):
            continue
        if name == norm or (root / child.name / "__init__.py").exists():
            dst = VENDOR / child.name
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(child, dst)
            copied += 1
            print("  ->", child.name)
    shutil.rmtree(tmp, ignore_errors=True)
    return copied > 0


if __name__ == "__main__":
    ok = True
    for name in sys.argv[1:]:
        ok = install(name) and ok
    print("OK" if ok else "PARTIAL")
