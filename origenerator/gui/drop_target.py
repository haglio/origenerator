"""A widget that takes drags wherever another part of the app says they land."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt

_DRAG_EVENTS = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)


class DropTarget(QObject):
    def __init__(self, widget, landing, drop):
        super().__init__(widget)
        self._landing = landing
        self._drop = drop
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def eventFilter(self, _watched, event):
        if event.type() not in _DRAG_EVENTS:
            return False
        landing = self._landing(event.mimeData(), event.source())
        if landing is None:
            event.ignore()
            return True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            self._drop(*landing)
        return True
