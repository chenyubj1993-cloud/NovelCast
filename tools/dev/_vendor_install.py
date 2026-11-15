# -*- coding: utf-8 -*-
"""把 openai 及其依赖的 wheel 直接解压到 .vendor（不依赖 pip，不写临时目录）。"""
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

VENDOR = Path(".vendor")
CACHE = Path(".wheels")
PACKAGES = [
    "openai", "httpx2", "httpcore2", "anyio", "distro", "jiter", "sniffio",
    "tqdm", "certifi", "idna", "h11", "pydantic", "pydantic-core",
    "annotated-types", "typing-extensions", "typing-inspection", "colorama",
    "truststore", "h2",
    "filelock", "sympy", "mpmath", "networkx", "jinja2", "markupsafe", "fsspec",
]


def pick_wheel(files):
    def score(name):
        if "macosx" in name or "manylinux" in name or "musllinux" in name:
            return -1
        if "cp312" in name and "win_amd64" in name:
            return 100
        if "cp312" in name and "abi3" in name and "win_amd64" in name:
            return 90
        if "py3-none-any" in name:
            return 50
        return -1

    scored = [(score(f["filename"]), f) for f in files if f["filename"].endswith(".whl")]
    scored = [(s, f) for s, f in scored if s > 0]
    if not scored:
        return None
    return max(scored, key=lambda x: x[0])[1]


def main():
    VENDOR.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    for pkg in PACKAGES:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=30) as r:
            meta = json.load(r)
        wheel = pick_wheel(meta["urls"])
        if not wheel:
            print(f"SKIP {pkg}: no compatible wheel")
            continue
        name = wheel["filename"]
        target = CACHE / name
        if not target.exists():
            with urllib.request.urlopen(wheel["url"], timeout=120) as r:
                target.write_bytes(r.read())
        with zipfile.ZipFile(target) as zf:
            zf.extractall(VENDOR)
        print(f"OK {pkg} {meta['info']['version']} -> {name}")


if __name__ == "__main__":
    sys.exit(main())
