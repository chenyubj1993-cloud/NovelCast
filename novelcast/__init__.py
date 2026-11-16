"""NovelCast: turn novels into multi-voice audiobooks."""
from __future__ import annotations

import sys
from pathlib import Path

# 本地依赖目录（pip 不可用时手工解压的 .vendor），存在时优先加载
_VENDOR = Path(__file__).resolve().parent.parent / ".vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

__version__ = "0.1.0"
