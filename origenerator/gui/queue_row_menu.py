from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QWidget

from origenerator.gui.inflight import CANCEL_ALL_BELOW_TEXT, jobs_below


def picks_cancel_below(over: QWidget, items: list, key: str, at: QPoint) -> bool:
    if not jobs_below(items, key):
        return False
    menu = QMenu(over)
    cancel_below = menu.addAction(CANCEL_ALL_BELOW_TEXT)
    return menu.exec(at) is cancel_below
