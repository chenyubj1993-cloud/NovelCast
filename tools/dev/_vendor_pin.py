# -*- coding: utf-8 -*-
"""按指定版本把 wheel 解压到 .vendor（IndexTTS-2 依赖）。"""
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

VENDOR = Path(".vendor")
CACHE = Path(".wheels")
PKGS = [line.strip() for line in """
accelerate==1.8.1
transformers==4.52.1
tokenizers==0.21.0
safetensors==0.5.2
huggingface-hub==0.33.5
sentencepiece
wetext
jieba==0.42.1
cn2an==0.5.22
omegaconf
munch==4.0.0
psutil
pyyaml
librosa==0.10.2.post1
numba==0.63.0
scipy
soundfile
audioread
pooch
soxr
lazy-loader
msgpack
einops
regex
packaging
descript-audiotools==0.7.2
requests
urllib3
charset-normalizer
openai-whisper
tiktoken
more-itertools
llvmlite==0.46.0
modelscope
modelscope_hub
cryptography
cffi
pycparser
pyjwt
edge-tts
aiohttp
aiohappyeyeballs
aiosignal
attrs
frozenlist
multidict
propcache
yarl
tabulate
flatten_dict
argbind
pyloudnorm
ffmpy
pystoi
docstring_parser
julius
importlib_resources
rich
markdown-it-py
pygments
mdurl
tensorboard
tensorboard-data-server
protobuf
absl-py
grpcio
markdown
werkzeug
randomname
kaldifst
setuptools
contractions
textsearch
pyahocorasick
anyascii
datasets
pyarrow
pillow
matplotlib
contourpy
cycler
fonttools
kiwisolver
pyparsing
python-dateutil
six
joblib
pandas
ffmpeg-python
cloudpickle
decorator
threadpoolctl
""".strip().splitlines() if line.strip()]


def pick(files):
    def score(name):
        if "macosx" in name or "manylinux" in name or "musllinux" in name:
            return -1
        if "cp312" in name and "win_amd64" in name:
            return 100
        if "py3-none-any" in name or "py2.py3-none-any" in name:
            return 50
        if "abi3" in name and "win_amd64" in name:
            return 80
        return -1

    cands = [f for f in files if f["filename"].endswith(".whl")]
    cands = [(score(f["filename"]), f) for f in cands]
    cands = [c for c in cands if c[0] > 0]
    return max(cands, key=lambda x: x[0])[1] if cands else None


def main():
    VENDOR.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    failed = []
    for spec in PKGS:
        name, _, ver = spec.partition("==")
        url = f"https://pypi.org/pypi/{name}/{ver}/json" if ver else f"https://pypi.org/pypi/{name}/json"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                meta = json.load(r)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL meta {spec}: {exc}")
            failed.append(spec)
            continue
        wheel = pick(meta["urls"])
        if not wheel:
            print(f"FAIL wheel {spec}")
            failed.append(spec)
            continue
        target = CACHE / wheel["filename"]
        if not target.exists():
            with urllib.request.urlopen(wheel["url"], timeout=180) as r:
                target.write_bytes(r.read())
        with zipfile.ZipFile(target) as zf:
            zf.extractall(VENDOR)
        print(f"OK {spec} -> {wheel['filename']}")
    if failed:
        print("FAILED:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
