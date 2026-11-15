"""从 ModelScope 下载 AISHELL-3 训练集的一个小子集（每人若干条）。

ModelScope 上的 saiting/AISHELL-3 镜像（3.4GB）包含 100 个训练集说话人，
比 HF 的测试集镜像（58 人、单句更短）更适合做音色库。

用法：
  python scripts/fetch_aishell3_modelscope.py --per-speaker 4 --workers 10
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API = "https://modelscope.cn/api/v1/datasets/{repo}/repo/tree?Revision=master&Root={root}&PageSize=100&PageNumber=1"
FILE = "https://modelscope.cn/datasets/{repo}/resolve/master/{path}"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _download(repo: str, path: str, dst: Path, timeout: int = 90) -> bool:
    if dst.exists() and dst.stat().st_size > 0:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            req = urllib.request.Request(FILE.format(repo=repo, path=path),
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
    parser.add_argument("--repo", default="saiting/AISHELL-3")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "aishell3_ms"))
    parser.add_argument("--per-speaker", type=int, default=4)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    spk_info = out / "spk-info.txt"
    if not spk_info.exists():
        _download(args.repo, "spk-info.txt", spk_info)

    print("📋 列出训练集说话人 …")
    listing = _get_json(API.format(repo=args.repo, root="/train/wav"))
    dirs = [f["Name"] for f in listing["Data"]["Files"] if f["Type"] == "tree"]
    print(f"   {len(dirs)} 个说话人")

    todo = []
    for spk in dirs:
        files = _get_json(API.format(repo=args.repo, root=f"/train/wav/{spk}"))["Data"]["Files"]
        wavs = [f["Name"] for f in files if f["Name"].endswith(".wav")]
        for name in wavs[: args.per_speaker]:
            rel = f"train/wav/{spk}/{name}"
            if not (out / rel).exists():
                todo.append(rel)
    print(f"   待下载 {len(todo)} 个")

    done = failed = 0
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
