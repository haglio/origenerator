from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractButton

from origenerator.gui.drag_thumbnail import DragOut
from origenerator.gui.drags import carry
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.enhance_versions import enhance_version_mime, params_from_mime
from origenerator.gui.folder_tree import folder_keys_in

FoldersSettings = Callable[[list[str]], dict | None]


def settings_carried(mime, folders_settings: FoldersSettings) -> dict | None:
    params = params_from_mime(mime)
    return params if params is not None else folders_settings(folder_keys_in(mime))


class EnhanceSettingsDrag(QObject):
    def __init__(self, widget, params_of: Callable[[], dict | None]):
        super().__init__(widget)
        self._widget = widget
        self._params_of = params_of
        self._gesture = DragOut()
        self._dragged = False
        widget.installEventFilter(self)

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
            self._let_go()
            return True
        return False

    def _let_go(self) -> None:
        if isinstance(self._widget, QAbstractButton):
            self._widget.setDown(False)

    def _carry(self, params: dict) -> None:
        self._dragged = True
        mime = enhance_version_mime(params)
        drag = QDrag(self._widget)
        drag.setMimeData(mime)
        carry(drag, mime, self._widget, Qt.DropAction.CopyAction)
        self._let_go()


class SettingsDropOnTheButton(QObject):
    def __init__(self, button, folders_settings: FoldersSettings, *,
                 takes_them: Callable[[], bool], keep: Callable[[dict], None]):
        super().__init__(button)
        self._folders_settings = folders_settings
        self._takes_them = takes_them
        DropTarget(button, self._landing, keep)

    def _landing(self, mime, _source) -> tuple[dict] | None:
        if not self._takes_them():
            return None
        params = settings_carried(mime, self._folders_settings)
        return None if params is None else (params,)
