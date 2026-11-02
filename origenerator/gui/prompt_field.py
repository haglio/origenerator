from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import BORDER_SUBTLE

DEFAULT_HEIGHT = 100
MAX_HEIGHT = 1600
GRIP = 6
_MARK_WIDTH = 24


class PromptHeights(QObject):
    changed = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._heights: dict[str, int] = {}

    def height(self, key: str) -> int:
        return self._heights.get(key, DEFAULT_HEIGHT)

    def set_height(self, key: str, height: int) -> None:
        height = min(int(height), MAX_HEIGHT)
        if height == self._heights.get(key):
            return
        self._heights[key] = height
        self.changed.emit(key, height)

    def snapshot(self) -> dict:
        return dict(self._heights)

    def restore(self, heights) -> None:
        previous = self._heights
        self._heights = {}
        if isinstance(heights, dict):
            for key, height in heights.items():
                if isinstance(key, str) and _is_number(height):
                    self._heights[key] = min(int(height), MAX_HEIGHT)
        for key in set(previous) | set(self._heights):
            if previous.get(key) != self._heights.get(key):
                self.changed.emit(key, self.height(key))


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


PROMPT_HEIGHTS = PromptHeights()


class PromptField(QPlainTextEdit):
    def __init__(self, key: str, parent=None, *, heights: PromptHeights | None = None):
        super().__init__(parent)
        self._key = key
        self._heights = heights or PROMPT_HEIGHTS
        self._drag: tuple[float, int] | None = None
        # Without tracking, the edge can only offer its resize cursor while a
        # button is already down — by which time you have clicked into the text.
        self.viewport().setMouseTracking(True)
        self._apply_height(self._heights.height(key))
        self._heights.changed.connect(self._on_shared_height_changed)

    def _on_shared_height_changed(self, key: str, height: int):
        if key == self._key:
            self._apply_height(height)

    def _apply_height(self, height: int):
        self.setFixedHeight(max(self._min_height(), min(int(height), MAX_HEIGHT)))

    def _min_height(self) -> int:
        chrome = max(self.height() - self.viewport().height(), 2 * self.frameWidth())
        return (self.fontMetrics().lineSpacing()
                + 2 * int(self.document().documentMargin()) + chrome)

    def _in_grip(self, pos) -> bool:
        """Is this point on the lower edge's grip?

        Mouse events on a scroll area arrive in *viewport* coordinates, so the
        grip is measured from the viewport's own lower edge — which also means the
        scrollbar, a child with its own events, is never part of it.
        """
        return pos.y() >= self.viewport().height() - GRIP

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._in_grip(event.position()):
            self._drag = (event.globalPosition().y(), self.height())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            grabbed_at, height = self._drag
            self._apply_height(int(height + event.globalPosition().y() - grabbed_at))
            event.accept()
            return
        self.viewport().setCursor(
            Qt.CursorShape.SizeVerCursor if self._in_grip(event.position())
            else Qt.CursorShape.IBeamCursor
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self._heights.set_height(self._key, self.height())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setPen(QPen(BORDER_SUBTLE, 1))
        middle = self.viewport().width() // 2
        lower = self.viewport().height() - 2
        for y in (lower, lower - 3):
            painter.drawLine(middle - _MARK_WIDTH // 2, y, middle + _MARK_WIDTH // 2, y)
        painter.end()

