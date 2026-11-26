"""零散小工具：WAV 时长读取、时长格式化与安全文件名。"""
from __future__ import annotations

import re
import wave

_INVALID_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_filename(name: str, max_len: int = 80) -> str:
    """把章节标题变成 Windows/Linux 都能用的文件名（去掉 / : ? 等）。"""
    cleaned = _INVALID_FILENAME.sub("_", (name or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned[:max_len] or "untitled"


def get_wav_duration(wav_path: str) -> float:
    """读取 WAV 时长（秒）。"""
    try:
        with wave.open(wav_path, "rb") as f:
            return f.getnframes() / f.getframerate()
    except (OSError, wave.Error, ZeroDivisionError):
        return 0.0


def format_duration(seconds: float) -> str:
    """格式化时长，如 "3:45" 或 "1:02:30"。"""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
