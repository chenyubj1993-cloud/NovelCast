"""兼容入口：`python scripts/generate.py ...`。

真正的实现已移到 `novelcast.engine`；推荐使用 `novelcast run` 或
`python -m novelcast run`。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.engine import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
