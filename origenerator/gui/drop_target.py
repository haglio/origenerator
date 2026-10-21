"""A drop zone that takes drags wherever another part of the app says they land."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractScrollArea

from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT, DropEdge, light

_DRAG_EVENTS = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)


class DropTarget(QObject):
    def __init__(self, zone, landing, drop):
        super().__init__(zone)
        self._zone = zone
        self._landing = landing
        self._drop = drop
        self._edge = DropEdge(zone)
        zone.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # to wear a ground of its own
        taker = zone.viewport() if isinstance(zone, QAbstractScrollArea) else zone
        taker.setAcceptDrops(True)
        taker.installEventFilter(self)
        under_way.started.connect(self._light_for)
        under_way.ended.connect(self._put_out)

    def _light_for(self, mime, source):
        self._wear(LIT, self._landing(mime, source) is not None)

    def _put_out(self):
        self._wear(LIT, False)
        self._wear(AIMED, False)

    def _wear(self, state, on):
        light(self._zone, state, on)
        self._edge.setVisible(bool(self._zone.property(LIT) or self._zone.property(AIMED)))

    def eventFilter(self, _watched, event):
        if event.type() == QEvent.Type.DragLeave:
            self._wear(AIMED, False)
        if event.type() not in _DRAG_EVENTS:
            return False
        landing = self._landing(event.mimeData(), event.source())
        self._wear(AIMED, landing is not None and event.type() != QEvent.Type.Drop)
        if landing is None:
            event.ignore()
            return True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            self._drop(*landing)
        return True
