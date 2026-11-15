"""从开源语音语料（默认 AISHELL-3）构建音色库。

流程：
  1. 扫描语料目录，按说话人分组；
  2. 对每条音频打分（时长是否接近 8–12s、语音占比、是否削顶）；
  3. 每个说话人取最高分的一条，裁到 <=12s，重采样 24k、峰值归一到 -6dBFS；
  4. 按性别均衡地挑 N 个说话人，写成 output/_refs/<voice_id>.wav；
  5. 生成 output/_refs/voice_bank.json，供 cast_manager.build_cast 选音色。

用法：
  python scripts/build_voice_bank.py D:\\data\\data_aishell3 --count 24
  python scripts/build_voice_bank.py <dir> --dry-run          # 只打分不写文件
  python scripts/build_voice_bank.py <dir> --speaker-glob "SSB*"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TARGET_SR = 24000
TARGET_DBFS = -6.0
MIN_SEC = 3.0
MAX_SEC = 12.0
IDEAL_SEC = 9.5

AGE_GROUPS = {"A": "child", "B": "young", "C": "adult", "D": "elder"}


def _find_speaker_dirs(root: Path, speaker_glob: str):
    """返回 [(speaker_id, [wav...])]，兼容 AISHELL-3 的 wav/<spk>/*.wav 结构。"""
    import fnmatch

    speakers = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        wavs = [f for f in filenames if f.lower().endswith(".wav")]
        if not wavs:
            continue
        for f in sorted(wavs):
            m = re.match(r"^(S\d{5})_", f)
            spk = m.group(1) if m else os.path.basename(dirpath)
            if speaker_glob and not fnmatch.fnmatch(spk, speaker_glob):
                continue
            if spk.lower() in ("wav", "wavs", "train", "test"):
                continue
            speakers.setdefault(spk, []).append(os.path.join(dirpath, f))
    return sorted(speakers.items())


def _load_speaker_info(root: Path):
    """解析 spk-info.txt：SSB0001\\tF\\t23 之类，返回 {spk: {gender, age}}。"""
    info = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            if "spk-info" not in f.lower():
                continue
            path = os.path.join(dirpath, f)
            try:
                lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line in lines:
                parts = [p.strip() for p in re.split(r"[\t ]+", line) if p.strip()]
                if len(parts) < 2:
                    continue
                spk = parts[0]
                gender = "unknown"
                age = "unknown"
                for p in parts[1:]:
                    if p.upper() in ("F", "FEMALE", "女"):
                        gender = "female"
                    elif p.upper() in ("M", "MALE", "男"):
                        gender = "male"
                    elif p.upper() in AGE_GROUPS:
                        age = AGE_GROUPS[p.upper()]
                    elif p.isdigit():
                        n = int(p)
                        if n < 18:
                            age = "child"
                        elif n < 30:
                            age = "young"
                        elif n < 50:
                            age = "adult"
                        else:
                            age = "elder"
                info[spk] = {"gender": gender, "age": age}
    return info


def _speech_ratio(y: "np.ndarray", sr: int) -> float:
    """用帧能量估计「有声」占比，避免依赖 librosa/sklearn。"""
    frame = max(1, int(0.025 * sr))
    hop = max(1, int(0.010 * sr))
    if len(y) < frame:
        return 1.0 if len(y) else 0.0
    n = 1 + (len(y) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    frames = y[idx]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    thr = max(1e-4, float(np.max(rms)) * 0.05)
    return float(np.mean(rms > thr))


def _analyse(path: str) -> dict:
    import soundfile as sf

    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    dur = len(y) / float(sr)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    return {"duration": dur, "peak": peak, "speech_ratio": _speech_ratio(y, sr), "sr": sr}


def _score(info: dict) -> float:
    dur = info["duration"]
    dur_score = max(0.0, 1.0 - abs(dur - IDEAL_SEC) / IDEAL_SEC)
    clip_penalty = 0.0 if info["peak"] < 0.98 else 0.4
    return 0.45 * dur_score + 0.45 * info["speech_ratio"] + 0.1 * (1.0 - clip_penalty)


def _make_reference(paths, out_path: Path) -> dict:
    import soundfile as sf
    import soxr

    parts = []
    sr = TARGET_SR
    for path in paths:
        y, sr = sf.read(path, dtype="float32", always_2d=True)
        parts.append(y.mean(axis=1))
    if len(parts) > 1:
        gap = np.zeros(int(0.15 * sr), dtype=np.float32)
        merged = []
        for p in parts:
            merged.extend([p, gap])
        y = np.concatenate(merged[:-1])
    else:
        y = parts[0]

    dur = len(y) / float(sr)
    if dur > MAX_SEC:
        # 从 10% 处开始截，避开开头可能的吸气/空白
        start = int(0.10 * len(y))
        n = int(MAX_SEC * sr)
        y = y[start:start + n]

    if sr != TARGET_SR:
        y = soxr.resample(y, sr, TARGET_SR)
        sr = TARGET_SR

    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0:
        target = 10 ** (TARGET_DBFS / 20.0)
        y = y * (target / peak)
    y = np.clip(y, -1.0, 1.0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), y.astype(np.float32), sr, subtype="PCM_16", format="WAV")
    return {"duration": round(len(y) / float(sr), 2), "samplerate": sr}


def _estimate_gender(path: str) -> str:
    """没有 spk-info 时用基频中位数粗判性别（165Hz 为界）。"""
    import soundfile as sf

    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    frame = int(0.04 * sr)
    hop = int(0.02 * sr)
    f0s = []
    for start in range(0, max(0, len(y) - frame), hop):
        seg = y[start:start + frame]
        if float(np.sqrt(np.mean(seg ** 2))) < 0.01:
            continue
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, "full")[frame - 1:]
        lo, hi = int(sr / 350), int(sr / 70)
        if hi >= len(corr) or corr[0] <= 0:
            continue
        lag = lo + int(np.argmax(corr[lo:hi]))
        if lag > 0 and corr[lag] > 0.3 * corr[0]:
            f0s.append(sr / lag)
    if len(f0s) < 10:
        return "unknown"
    return "female" if float(np.median(f0s)) > 165 else "male"


def _sanitize_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", text).strip("-") or "voice"


def main() -> int:
    parser = argparse.ArgumentParser(description="从 AISHELL-3 等语料构建 voice bank")
    parser.add_argument("source", help="语料根目录（含 wav/<speaker>/*.wav）")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "output" / "_refs"), help="参考音输出目录")
    parser.add_argument("--count", type=int, default=24, help="最多挑多少个说话人")
    parser.add_argument("--per-speaker", type=int, default=1, help="兼容参数，已忽略（每人 1 条，短句自动拼接）")
    parser.add_argument("--speaker-glob", default="", help="只处理匹配的说话人目录，如 SSB*")
    parser.add_argument("--dry-run", action="store_true", help="只评分，不写任何文件")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--style", default="read", help="broadcast / read / storytelling")
    parser.add_argument("--source-name", default="aishell3", help="写进 bank 的来源标记")
    parser.add_argument("--id-prefix", default="A3", help="音色 id 前缀")
    parser.add_argument("--infer-gender", action="store_true", help="没有 spk-info 时用基频判断性别")
    parser.add_argument("--merge", action="store_true", help="合并进已有 voice_bank.json 而不是覆盖")
    args = parser.parse_args()

    root = Path(args.source)
    if not root.is_dir():
        print(f"目录不存在: {root}")
        return 2

    print(f"🔍 扫描 {root} ...")
    speaker_dirs = _find_speaker_dirs(root, args.speaker_glob)
    print(f"   说话人 {len(speaker_dirs)} 个")
    if not speaker_dirs:
        print("没找到 wav 文件，检查 --speaker-glob 或目录结构")
        return 2

    spk_info = _load_speaker_info(root)
    print(f"   说话人元信息 {len(spk_info)} 条")

    candidates = []
    for spk, wavs in speaker_dirs:
        scored = []
        for wav in wavs:
            try:
                info = _analyse(wav)
            except Exception as exc:  # noqa: BLE001
                print(f"   ⚠️ 跳过 {os.path.basename(wav)}: {exc}")
                continue
            if info["duration"] < 0.8:
                # 单句太短的先留着，后面会和同说话人的其它句子拼起来
                continue
            info["path"] = wav
            info["score"] = _score(info)
            scored.append(info)
        scored.sort(key=lambda x: x["score"], reverse=True)
        meta = spk_info.get(spk, {})

        # 单条太短时，把同一说话人的高分句拼起来凑到 ~9.5 秒
        chosen = []
        used_secs = 0.0
        for info in scored:
            if used_secs >= IDEAL_SEC:
                break
            if used_secs + info["duration"] > MAX_SEC and used_secs >= MIN_SEC:
                break
            chosen.append(info)
            used_secs += info["duration"]
        if used_secs < MIN_SEC:
            continue
        gender = meta.get("gender", "unknown")
        if gender == "unknown" and args.infer_gender:
            gender = _estimate_gender(chosen[0]["path"])
        candidates.append({
            "speaker": spk,
            "paths": [c["path"] for c in chosen],
            "gender": gender,
            "age": meta.get("age", "unknown"),
            "score": round(max(c["score"] for c in chosen), 4),
            "duration": round(used_secs, 2),
            "speech_ratio": round(
                sum(c["speech_ratio"] * c["duration"] for c in chosen) / used_secs, 3),
            "peak": round(max(c["peak"] for c in chosen), 3),
        })

    if not candidates:
        print("没有满足时长要求的音频")
        return 2

    # 性别均衡：female / male / unknown 轮流取
    rng = np.random.RandomState(args.seed)
    groups = {"female": [], "male": [], "unknown": []}
    for c in sorted(candidates, key=lambda x: x["score"], reverse=True):
        groups.setdefault(c["gender"], []).append(c)
    for key in groups:
        rng.shuffle(groups[key])
        groups[key].sort(key=lambda x: x["score"], reverse=True)

    picked = []
    order = ["female", "male", "unknown"]
    while len(picked) < args.count and any(groups[g] for g in order):
        for g in order:
            if groups[g] and len(picked) < args.count:
                picked.append(groups[g].pop(0))

    refs_dir = Path(args.out)
    entries = []
    for i, c in enumerate(picked, 1):
        voice_id = f"{args.id_prefix}-{_sanitize_id(c['speaker'])}"
        if args.per_speaker > 1:
            voice_id = f"{voice_id}-{i:02d}"
        out_path = refs_dir / f"{voice_id}.wav"
        if args.dry_run:
            print(f"   [dry] {voice_id}: {c['score']:.3f} {c['duration']}s {c['gender']} <- {c['paths'][0]}")
            continue
        try:
            made = _make_reference(c["paths"], out_path)
        except Exception as exc:  # noqa: BLE001
            print(f"   ⚠️ 生成失败 {voice_id}: {exc}")
            continue
        entries.append({
            "id": voice_id,
            "name": voice_id,
            "path": f"{voice_id}.wav",
            "gender": c["gender"],
            "age": c["age"],
            "source": args.source_name,
            "style": args.style,
            "speaker": c["speaker"],
            "duration": made["duration"],
            "sample_rate": made["samplerate"],
            "score": c["score"],
        })
        print(f"   ✅ {voice_id:20s} {created_tag(c)} {c['gender']:6s} {made['duration']:5.1f}s score={c['score']:.3f}")

    if args.dry_run:
        return 0

    bank_path = refs_dir / "voice_bank.json"
    old_voices = []
    if args.merge and bank_path.exists():
        try:
            old = json.loads(bank_path.read_text(encoding="utf-8"))
            new_ids = {e["id"] for e in entries}
            old_voices = [v for v in old.get("voices", []) if v.get("id") not in new_ids]
        except (OSError, ValueError):
            old_voices = []
    all_voices = old_voices + entries
    bank = {
        "version": 1,
        "source": "mixed" if old_voices else args.source_name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target_sample_rate": TARGET_SR,
        "target_dbfs": TARGET_DBFS,
        "voices": all_voices,
    }
    bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n🎚️  已写入 {len(entries)} 个音色（库内共 {len(all_voices)}）-> {bank_path}")
    print(f"   参考音目录: {refs_dir}")
    return 0


def created_tag(c: dict) -> str:
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
