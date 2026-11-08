from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QWidget

_SHOWN_OR_HIDDEN = (QEvent.Type.ShowToParent, QEvent.Type.HideToParent)


class ItemArea(QObject):
    def __init__(self, area: QWidget, sections: tuple[QWidget, ...], *,
                 on_shown: Callable[[], None]):
        super().__init__(area)
        self._area = area
        self._sections = sections
        self._on_shown = on_shown
        for section in sections:
            section.installEventFilter(self)
        self._follow()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in _SHOWN_OR_HIDDEN:
            self._follow()
        return False

    def _follow(self) -> None:
        showing = any(not section.isHidden() for section in self._sections)
        appearing = showing and self._area.isHidden()
        self._area.setVisible(showing)
        if appearing:
            self._on_shown()
