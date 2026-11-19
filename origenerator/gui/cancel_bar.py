from __future__ import annotations

from PySide6.QtCore import Qt, Signal

from origenerator.gui.deferred import defer
from origenerator.gui.inflight import CANCEL_TEXT
from origenerator.gui.progress_bar import ProgressBar


class CancelBar(ProgressBar):
    clicked = Signal()

    def __init__(self, tooltip: str, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._cancelable = True
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_cancelable(self, cancelable: bool) -> None:
        self._cancelable = cancelable
        self.setCursor(Qt.CursorShape.PointingHandCursor if cancelable
                       else Qt.CursorShape.ArrowCursor)
        self.update()

    def text(self) -> str:
        return CANCEL_TEXT if self._hovered and self._cancelable else super().text()

    def enterEvent(self, event):
        self._hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover(False)
        super().leaveEvent(event)

    def _hover(self, hovered: bool) -> None:
        self._hovered = hovered
        self.retime_scroll()
        self.update()

    def _cancel_once_the_release_has_reached_the_bar(self) -> None:
        self.clicked.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._cancelable:
            event.accept()
            defer(self, self._cancel_once_the_release_has_reached_the_bar)
            return
        super().mousePressEvent(event)
