# -*- coding: utf-8 -*-
"""分级日志：支持 -q / -v、JSON 模式静默，以及 GUI 日志回调。"""
from __future__ import annotations

import sys
from typing import Callable, List

#: 日志级别
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
SILENT = 100

_LEVEL_NAMES = {DEBUG: "DEBUG", INFO: "", WARNING: "警告", ERROR: "错误"}

#: GUI 日志回调：(文本, 级别) -> None
_handlers: List[Callable[[str, int], None]] = []

#: 当前最低输出级别
_level = INFO


def set_level(level: int) -> None:
    global _level
    _level = level


def get_level() -> int:
    return _level


def add_handler(handler: Callable[[str, int], None]) -> None:
    _handlers.append(handler)


def remove_handler(handler: Callable[[str, int], None]) -> None:
    if handler in _handlers:
        _handlers.remove(handler)


class Logger(object):
    """一个带名字的小日志器。"""

    def __init__(self, name: str = "") -> None:
        self.name = name

    def _emit(self, level: int, message: str) -> None:
        if level < _level or _level >= SILENT:
            return
        prefix = _LEVEL_NAMES.get(level, "")
        text = ("[{0}] ".format(prefix) if prefix else "") + message
        for handler in list(_handlers):
            try:
                handler(text, level)
            except Exception:
                pass
        if not _handlers:
            stream = sys.stderr if level >= WARNING else sys.stdout
            try:
                print(text, file=stream, flush=True)
            except Exception:
                pass

    def debug(self, message: str, *args) -> None:
        self._emit(DEBUG, self._format(message, args))

    def info(self, message: str = "", *args) -> None:
        self._emit(INFO, self._format(message, args))

    def warning(self, message: str, *args) -> None:
        self._emit(WARNING, self._format(message, args))

    def error(self, message: str, *args) -> None:
        self._emit(ERROR, self._format(message, args))

    def progress(self, message: str, *args) -> None:
        """进度提示：与 info 同级别，但便于 GUI 单独着色。"""
        self._emit(INFO, self._format(message, args))

    @staticmethod
    def _format(message: str, args) -> str:
        if not args:
            return str(message)
        try:
            return str(message) % args
        except Exception:
            return " ".join([str(message)] + [str(a) for a in args])


def get_logger(name: str = "") -> Logger:
    return Logger(name)
