from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLineEdit, QToolButton
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import draw_icon
from shared_ui.spacing import BUTTON_ICON, GAP_SMALL

_ONE_TURN_MS = 1000
_CIRCLE_ROOM = BUTTON_ICON + 2 * GAP_SMALL
_PREFIX = "Search "
_TRAILING = "…"
_CHROME = 12


class ScopeSearchEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scope = ""
        self._turned: float | None = None
        self._turning = QVariantAnimation(self)
        self._turning.setStartValue(0.0)
        self._turning.setEndValue(360.0)
        self._turning.setDuration(_ONE_TURN_MS)
        self._turning.setLoopCount(-1)
        self._turning.valueChanged.connect(self._turn_the_circle)
        self._render_placeholder()

    def working(self) -> bool:
        return self._turned is not None

    def set_working(self, working: bool):
        if working == self.working():
            return
        self._turned = 0.0 if working else None
        self.setTextMargins(0, 0, _CIRCLE_ROOM if working else 0, 0)
        if working:
            self._turning.start()
        else:
            self._turning.stop()
        self.update()

    def set_scope(self, path: str):
        if path != self._scope:
            self._scope = path
            self._render_placeholder()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_placeholder()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._turned is None:
            return
        box = self._circle_box()
        painter = QPainter(self)
        painter.translate(box.center())
        painter.rotate(self._turned)
        painter.translate(-box.center())
        draw_icon(painter, "working", TEXT_SECONDARY, size=box.width(), x=box.x(), y=box.y())
        painter.end()

    def _circle_box(self) -> QRectF:
        end = min((button.geometry().left() for button in self.findChildren(QToolButton)
                   if button.isVisibleTo(self)), default=self.contentsRect().right())
        return QRectF(end - _CIRCLE_ROOM + GAP_SMALL, (self.height() - BUTTON_ICON) / 2,
                      BUTTON_ICON, BUTTON_ICON)

    def _turn_the_circle(self, degrees):
        self._turned = degrees
        self.update()

    def _render_placeholder(self):
        metrics = self.fontMetrics()
        room = (self.contentsRect().width() - _CHROME
                - metrics.horizontalAdvance(_PREFIX + _TRAILING))
        path = metrics.elidedText(self._scope, Qt.TextElideMode.ElideLeft,
                                  max(room, 0))
        tail = _TRAILING if path == self._scope else ""
        self.setPlaceholderText(f"{_PREFIX}{path}{tail}")
