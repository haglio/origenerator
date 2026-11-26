from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


def spin_the_pointer() -> Callable[[], None]:
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    # Qt shows the override cursor only on a turn of its event loop, which the work would block.
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    return QApplication.restoreOverrideCursor
