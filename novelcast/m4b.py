"""把逐章 WAV 封装成带章节标记的 M4B（需要系统里有 ffmpeg）。

M4B 只是 MP4 容器 + AAC 音频 + 章节元数据，封装交给 ffmpeg；
这里负责算时间轴、写 ffmetadata、拼 concat 列表，并在缺少 ffmpeg 时给出可操作的报错。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import List, Optional, Sequence

from novelcast.log import log


class M4BError(RuntimeError):
    """封装 M4B 失败（通常是缺 ffmpeg 或输入不可读）。"""


def wav_duration(path: Path) -> float:
    """读 PCM WAV 的时长（秒）。"""
    with wave.open(str(path), "rb") as fh:
        frames = fh.getnframes()
        rate = fh.getframerate() or 1
    return frames / float(rate)


def _escape(value: str) -> str:
    # ffmetadata 的转义规则：\ = ; # 换行都要处理
    text = str(value).replace("\\", "\\\\")
    for ch in ("=", ";", "#"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", " ").replace("\r", " ")


def chapter_marks(
    durations: Sequence[float], titles: Sequence[str]
) -> List[dict]:
    """把每章时长换算成 [start_ms, end_ms) 时间轴。"""
    if len(durations) != len(titles):
        raise ValueError("durations 与 titles 数量不一致")
    marks = []
    cursor = 0
    for seconds, title in zip(durations, titles):
        start = cursor
        end = cursor + max(0, int(round(seconds * 1000)))
        marks.append({"title": title, "start_ms": start, "end_ms": end})
        cursor = end
    return marks


def ffmetadata_text(
    marks: Sequence[dict],
    title: Optional[str] = None,
    artist: Optional[str] = None,
) -> str:
    """生成 ffmpeg 的 ffmetadata 文本（章节 + 书名/作者）。"""
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={_escape(title)}")
    if artist:
        lines.append(f"artist={_escape(artist)}")
    for mark in marks:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={mark['start_ms']}",
            f"END={mark['end_ms']}",
            f"title={_escape(mark['title'])}",
        ]
    return "\n".join(lines) + "\n"


def _concat_list(path: Path, wav_paths: Sequence[Path]) -> None:
    rows = []
    for wav in wav_paths:
        # concat demuxer 的单引号需要转义
        rows.append("file '" + os.path.abspath(wav).replace("'", "'\\''") + "'")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def build_m4b(
    wav_paths: Sequence[Path],
    titles: Sequence[str],
    output_path: Path,
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    bitrate: str = "128k",
) -> Path:
    """把章节 WAV 合并成带章节的 .m4b，返回输出路径。"""
    wav_paths = [Path(p) for p in wav_paths]
    if not wav_paths:
        raise M4BError("没有可封装的音频")
    if len(wav_paths) != len(titles):
        raise ValueError("wav_paths 与 titles 数量不一致")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise M4BError(
            "未找到 ffmpeg，无法导出 M4B。请先安装 ffmpeg 并加入 PATH：\n"
            "  Windows: winget install Gyan.FFmpeg  或从 https://ffmpeg.org/download.html 下载\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )

    durations = [wav_duration(p) for p in wav_paths]
    marks = chapter_marks(durations, titles)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part = output_path.parent / (output_path.name + ".part")
    if part.exists():
        part.unlink()

    with tempfile.TemporaryDirectory(prefix="novelcast_m4b_") as tmp:
        tmp_dir = Path(tmp)
        list_file = tmp_dir / "concat.txt"
        meta_file = tmp_dir / "meta.txt"
        _concat_list(list_file, wav_paths)
        meta_file.write_text(
            ffmetadata_text(marks, title=title, artist=artist), encoding="utf-8"
        )
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-i", str(meta_file),
            "-map", "0:a",
            "-map_metadata", "1",
            "-c:a", "aac",
            "-b:a", bitrate,
            "-movflags", "+faststart",
            "-f", "mp4",
            str(part),
        ]
        log.info(f"📦 封装 M4B：{output_path.name}（{len(wav_paths)} 章，{sum(durations) / 60:.1f} 分钟）")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            part.unlink(missing_ok=True)
            raise M4BError("ffmpeg 封装超时（30 分钟）")
        if proc.returncode != 0:
            part.unlink(missing_ok=True)
            detail = (proc.stderr or "").strip().splitlines()[-3:]
            raise M4BError("ffmpeg 封装失败：" + " | ".join(detail))
    if not part.exists() or part.stat().st_size == 0:
        raise M4BError("ffmpeg 没有产出 M4B 文件")
    os.replace(part, output_path)
    return output_path
