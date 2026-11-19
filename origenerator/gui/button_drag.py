from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDrag

from origenerator.gui.drag_thumbnail import DragOut
from origenerator.gui.drags import carry
from origenerator.gui.enhance_versions import enhance_version_mime


class EnhanceSettingsDrag(QObject):
    def __init__(self, button, params_of: Callable[[], dict | None]):
        super().__init__(button)
        self._button = button
        self._params_of = params_of
        self._gesture = DragOut()
        self._dragged = False
        button.installEventFilter(self)

    def eventFilter(self, _watched, event):  # noqa: N802 -- Qt's name
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            self._dragged = False
            self._gesture.note_press(event)
        elif kind == QEvent.Type.MouseMove and self._gesture.should_start(event):
            params = self._params_of()
            if params is not None:
                self._carry(params)
                return True
        elif kind == QEvent.Type.MouseButtonRelease and self._dragged:
            self._dragged = False
            self._button.setDown(False)
            return True
        return False

    def _carry(self, params: dict) -> None:
        self._dragged = True
        mime = enhance_version_mime(params)
        drag = QDrag(self._button)
        drag.setMimeData(mime)
        carry(drag, mime, self._button, Qt.DropAction.CopyAction)
        self._button.setDown(False)
