from __future__ import annotations

import logging

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
from shared_ui.qt_messages import silence_the_ffmpeg_format_dump

_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

logger = logging.getLogger("qt")


_FIRST_ROUND_NUMBER = 10


def _a_round_number(count: int) -> bool:
    return count >= _FIRST_ROUND_NUMBER and 10 ** (len(str(count)) - 1) == count


class RepeatCollapser:
    def __init__(self, say) -> None:
        self._say = say
        self._last: tuple[int, str] | None = None
        self._repeats = 0

    def __call__(self, level: int, message: str) -> None:
        if (level, message) == self._last:
            self._repeats += 1
            if _a_round_number(self._repeats):
                self._say(level, f"{message} ({self._repeats} more of these so far)")
            return
        self.flush()
        self._last = (level, message)
        self._say(level, message)

    def flush(self) -> None:
        if self._last is not None and self._repeats:
            level, message = self._last
            self._say(level, f"{message} ({self._repeats + 1} of these in all)")
        self._last, self._repeats = None, 0


def install_qt_message_logging():
    silence_the_ffmpeg_format_dump()
    collapse = RepeatCollapser(lambda level, message: logger.log(level, "%s", message))

    def log_qt_message(kind, _context, message: str) -> None:
        collapse(_LEVELS.get(kind, logging.WARNING), message)

    return qInstallMessageHandler(log_qt_message)
