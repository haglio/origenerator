from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _UnderWay(QObject):
    started = Signal(object, object)
    ended = Signal()


under_way = _UnderWay()


def carry(drag, mime, source, action) -> None:
    under_way.started.emit(mime, source)
    try:
        drag.exec(action)
    finally:
        under_way.ended.emit()
