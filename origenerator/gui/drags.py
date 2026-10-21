"""Every drag the app starts, told to every place a drop can land: wherever it
starts, it goes through :func:`carry`, and every such place hears :data:`under_way`."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class _UnderWay(QObject):
    started = pyqtSignal(object, object)  # the payload (QMimeData) and the drag's source
    ended = pyqtSignal()


under_way = _UnderWay()


def carry(drag, mime, source, action) -> None:
    under_way.started.emit(mime, source)
    try:
        drag.exec(action)
    finally:
        under_way.ended.emit()
