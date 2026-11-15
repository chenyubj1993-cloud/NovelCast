"""从 ModelScope 流式下载 WenetSpeech4TTS Premium 子集的一小部分。

数据是 tar.gz 大包（单个 8.5GB），这里不落整包：边下边解，只保留
前 N 个说话人、每人 M 条，够建音色库就主动断开。

用法:
    python scripts/fetch_ws4tts.py --speakers 60 --per-speaker 10
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
import tarfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

BASE = ("https://modelscope.cn/datasets/dukguo/WenetSpeech4TTS/"
        "resolve/master/Premium/WenetSpeech4TTS_Premium_{part}.tar.gz")
SPK_RE = re.compile(r"_(S\d{5})\.wav$")


class CountingReader:
    """给 tarfile 一个只读、不可 seek 的流，同时记录已读字节。"""

    def __init__(self, fp):
        self.fp = fp
        self.bytes = 0

    def read(self, n=-1):
        data = self.fp.read(n)
        self.bytes += len(data)
        return data

    def readinto(self, buf):
        data = self.fp.read(len(buf))
        buf[: len(data)] = data
        self.bytes += len(data)
        return len(data)

    def close(self):
        self.fp.close()

    def seekable(self):
        return False

    def readable(self):
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ws4tts")
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--speakers", type=int, default=60)
    ap.add_argument("--per-speaker", type=int, default=10)
    ap.add_argument("--max-bytes", type=int, default=2_500_000_000)
    args = ap.parse_args()

    out = Path(args.out)
    wav_dir = out / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)

    url = BASE.format(part=args.part)
    print(f"GET {url}")
    counts: Counter[str] = Counter()
    done_spk: set[str] = set()
    got = 0
    t0 = time.time()

    resp = urllib.request.urlopen(url, timeout=120)
    reader = CountingReader(resp)
    gz = gzip.GzipFile(fileobj=reader, mode="rb")  # type: ignore[arg-type]
    try:
        with tarfile.open(fileobj=gz, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".wav"):
                    continue
                m = SPK_RE.search(member.name)
                if not m:
                    continue
                spk = m.group(1)
                if spk in done_spk:
                    continue
                if counts[spk] >= args.per_speaker:
                    done_spk.add(spk)
                    if len(done_spk) >= args.speakers:
                        print(f"够 {len(done_spk)} 个说话人了，停止下载")
                        break
                    continue
                fh = tar.extractfile(member)
                if fh is None:
                    continue
                data = fh.read()
                (wav_dir / f"{spk}_{counts[spk]:03d}.wav").write_bytes(data)
                counts[spk] += 1
                got += 1
                if got % 50 == 0:
                    print(f"  {got} 条 / {len(counts)} 人 / {reader.bytes/1e6:.0f}MB / {time.time()-t0:.0f}s")
                if reader.bytes > args.max_bytes:
                    print("达到体积上限，停止")
                    break
    except Exception as exc:  # 主动断开时会抛，属于正常结束
        print(f"停止: {type(exc).__name__}: {exc}")
    finally:
        try:
            gz.close()
        finally:
            resp.close()

    print(f"完成: {got} 条, {len(counts)} 个说话人, {reader.bytes/1e6:.0f}MB, 输出 {out}")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
