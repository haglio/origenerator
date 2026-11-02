from __future__ import annotations

from contextlib import contextmanager

from PyQt6.QtCore import QEventLoop, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication


@contextmanager
def working():
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    # Qt shows the override cursor only on a turn of its event loop, which the work would block.
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
