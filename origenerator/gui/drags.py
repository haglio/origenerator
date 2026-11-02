from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class _UnderWay(QObject):
    started = pyqtSignal(object, object)
    ended = pyqtSignal()


under_way = _UnderWay()


def carry(drag, mime, source, action) -> None:
    under_way.started.emit(mime, source)
    try:
        drag.exec(action)
    finally:
        under_way.ended.emit()
