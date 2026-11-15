"""统一日志入口。

库代码里原来到处是 print()，改成 logging 之后：
- --quiet 只保留错误；
- --verbose 打开 debug；
- 输出走 stdout，格式仍是纯文本，方便管道/重定向。
"""
from __future__ import annotations

import logging
import sys

_LOGGER = logging.getLogger("novelcast")
_FORMAT = "%(message)s"


def setup(verbose: bool = False, quiet: bool = False) -> None:
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    _LOGGER.handlers[:] = [handler]
    _LOGGER.setLevel(level)
    _LOGGER.propagate = False


class _Log:
    """薄封装：保留 f-string 拼好的消息，不做 % 格式化。"""

    def debug(self, message: str) -> None:
        _LOGGER.debug(message)

    def info(self, message: str) -> None:
        _LOGGER.info(message)

    def warning(self, message: str) -> None:
        _LOGGER.warning(message)

    def error(self, message: str) -> None:
        _LOGGER.error(message)


log = _Log()
