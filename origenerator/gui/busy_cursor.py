from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


@contextmanager
def working():
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    # Qt shows the override cursor only on a turn of its event loop, which the work would block.
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
