"""Qt's own messages, in the app's log, without letting one of them flood it.

Qt repeats a message as often as the thing it complains about happens, which
for anything per-frame is thousands of times a minute: "Failed to activate
audio device" arrived 30,000 times in three minutes on 2026-09-17, which is
every rotation of origenerator.log spent and every older line in it gone.  A
log that keeps four megabytes can hold weeks of an app's own record or three
minutes of one complaint, so a run of the same message is said once, counted,
and said again with its count when the run ends.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

logger = logging.getLogger("qt")


def _a_round_number(count: int) -> bool:
    """Whether *count* is a power of ten from ten up, which is when a run still
    going says how far it has got.

    A flood that never ends -- the app killed while it is still arriving -- would
    otherwise leave one line and no sign of how bad it was; nine of these cover a
    run of ten billion.  From ten, so a message said twice is not said three
    times.
    """
    return count >= 10 and 10 ** (len(str(count)) - 1) == count


class RepeatCollapser:
    """One line per run of an identical message, plus the count of the rest."""

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
        """Say what a finished run came to, and forget it."""
        if self._last is not None and self._repeats:
            level, message = self._last
            self._say(level, f"{message} ({self._repeats + 1} of these in all)")
        self._last, self._repeats = None, 0


_collapse = RepeatCollapser(lambda level, message: logger.log(level, "%s", message))


def log_qt_message(kind, _context, message: str) -> None:
    _collapse(_LEVELS.get(kind, logging.WARNING), message)


def install_qt_message_logging():
    return qInstallMessageHandler(log_qt_message)
