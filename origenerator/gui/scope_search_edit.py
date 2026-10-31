"""The gallery's search field: a line edit whose placeholder names what it covers.

The tree's selection is the search's scope, and the thing that says which folder
that is, is its whole path — a folder is named by a short code, and a code on its
own says nothing about which branch it sits in. So the field holds the full
breadcrumb and elides it from the left when the pane is too narrow for all of it:
the tail is the folder itself and its nearest parents, which is the half that
answers "search where?".
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QLineEdit, QToolButton
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import draw_icon
from shared_ui.spacing import BUTTON_ICON, GAP_SMALL

_ONE_TURN_MS = 1000
_CIRCLE_ROOM = BUTTON_ICON + 2 * GAP_SMALL
# What the placeholder says around the path, and the room its own characters take.
_PREFIX = "Search "
_TRAILING = "…"
# Slack for the frame, the text margin and whatever padding the stylesheet adds:
# measured room that isn't accounted for reads as a path that fits when it
# doesn't, and the last few characters of the folder's own name are the ones
# that get clipped.
_CHROME = 12


class ScopeSearchEdit(QLineEdit):
    """A search field that says, in its placeholder, which folder a query would
    search — the whole path, elided from the left to whatever the field is wide."""

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
        """Name the folder a query typed here would search."""
        if path != self._scope:
            self._scope = path
            self._render_placeholder()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_placeholder()  # a wider pane shows more of the path

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
        # The trailing ellipsis is the "type here" one, and it goes when the path
        # is already wearing a leading one: two in a line read as a truncation at
        # both ends rather than as an invitation.
        tail = _TRAILING if path == self._scope else ""
        self.setPlaceholderText(f"{_PREFIX}{path}{tail}")
