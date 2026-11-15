"""从 HuggingFace 镜像并发下载 AISHELL-3 的测试集（小体积，足够构建音色库）。

AISHELL/AISHELL-3 仓库的 test 划分：790 个 wav、58 个说话人、约 130MB。

用法：
  python scripts/fetch_aishell3_subset.py --speakers 58 --per-speaker 14 --workers 12
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TREE_API = "https://hf-mirror.com/api/datasets/{repo}/tree/main?recursive=true"
RESOLVE = "https://hf-mirror.com/datasets/{repo}/resolve/main/{path}"


def _download(repo: str, rel: str, dst: Path, timeout: int = 90) -> bool:
    if dst.exists() and dst.stat().st_size > 0:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            req = urllib.request.Request(RESOLVE.format(repo=repo, path=rel),
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data:
                dst.write_bytes(data)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="AISHELL/AISHELL-3")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "aishell3_hf"))
    parser.add_argument("--speakers", type=int, default=58)
    parser.add_argument("--per-speaker", type=int, default=14)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"📋 拉取文件列表 {TREE_API.format(repo=args.repo)}")
    with urllib.request.urlopen(TREE_API.format(repo=args.repo), timeout=120) as r:
        tree = json.load(r)
    wavs = [x["path"] for x in tree if x.get("type") == "file" and x["path"].endswith(".wav")]
    spk = Counter(p.split("/")[2] for p in wavs if p.count("/") >= 3)
    print(f"   共 {len(wavs)} 个 wav，{len(spk)} 个说话人")

    info_path = out / "spk-info.txt"
    if not info_path.exists():
        _download(args.repo, "spk-info.txt", info_path)

    chosen = list(spk)[: args.speakers]
    todo = []
    for s in chosen:
        for rel in [p for p in wavs if p.split("/")[2] == s][: args.per_speaker]:
            dst = out / rel
            if not (dst.exists() and dst.stat().st_size > 0):
                todo.append(rel)
    print(f"   待下载 {len(todo)} 个")

    done = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_download, args.repo, rel, out / rel): rel for rel in todo}
        for fut in as_completed(futures):
            if fut.result():
                done += 1
            else:
                failed += 1
            if (done + failed) % 50 == 0:
                print(f"   … {done + failed}/{len(todo)}")

    total = sum(f.stat().st_size for f in out.rglob("*.wav"))
    print(f"✅ 成功 {done}，失败 {failed}，共 {total/1e6:.1f} MB -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
