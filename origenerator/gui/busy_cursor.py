"""The cursor that says a click is being worked on."""
from __future__ import annotations

from contextlib import contextmanager

from PyQt6.QtCore import QEventLoop, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication


@contextmanager
def working():
    """The waiting cursor for as long as the block runs, pushed through before
    the work starts since the work is what stops Qt taking a turn."""
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
