"""Every drag the app starts, announced to every place a drop can land.

The sources are scattered -- a thumbnail, a Generate tab's preview, a version
row, a folder in the TOC -- and so are the places that take what they carry, so
each source hands its drag to :func:`carry` and each place listens to
:data:`under_way`, lighting while a drag it would take is in flight.
"""
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
