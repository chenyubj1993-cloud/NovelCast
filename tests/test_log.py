# -*- coding: utf-8 -*-
"""log 单元测试：setup 级别切换、默认 handler 与 stdout 输出。"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import log as log_module


@pytest.fixture(autouse=True)
def _restore_logger():
    """setup() 会替换全局 logger 的 handler，测试后恢复，避免影响其它用例。"""
    logger = log_module._LOGGER
    handlers = logger.handlers[:]
    level = logger.level
    propagate = logger.propagate
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def test_default_handler_writes_to_stdout():
    logger = log_module._LOGGER

    assert logger.propagate is False
    assert logger.handlers, "导入时应已注册默认 handler"
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.formatter is not None
    assert handler.formatter._fmt == "%(message)s"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, logging.INFO),
        ({"verbose": True}, logging.DEBUG),
        ({"quiet": True}, logging.ERROR),
    ],
)
def test_setup_levels(kwargs, expected):
    log_module.setup(**kwargs)

    assert log_module._LOGGER.level == expected


def test_setup_keeps_single_handler():
    log_module.setup()
    log_module.setup(verbose=True)

    assert len(log_module._LOGGER.handlers) == 1


def test_info_goes_to_stdout(capsys):
    log_module.setup()
    log_module.log.info("信息-写入-stdout")

    captured = capsys.readouterr()

    assert "信息-写入-stdout" in captured.out
    assert captured.err == ""


def test_quiet_suppresses_info_but_keeps_error(capsys):
    log_module.setup(quiet=True)
    log_module.log.info("这条不应出现")
    log_module.log.debug("调试也不应出现")

    assert capsys.readouterr().out == ""

    log_module.log.error("错误仍然可见")
    assert "错误仍然可见" in capsys.readouterr().out


def test_verbose_enables_debug(capsys):
    log_module.setup(verbose=True)
    log_module.log.debug("调试-可见")

    assert "调试-可见" in capsys.readouterr().out
