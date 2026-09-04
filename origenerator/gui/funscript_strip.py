"""A thin funscript heatmap painted under a video preview.

Proof at a glance that a clip has a stroke script — and what its motion looks
like — mirroring the strip the sibling Nau player shows. Colors come from
``funscript.heatmap_colors`` (one per pixel column); this widget only paints.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from origenerator.funscript import heatmap_colors

_STRIP_HEIGHT = 14
_EMPTY = QColor(30, 30, 30)  # no script: a flat, obviously inert bar


class FunscriptStrip(QWidget):
    """Renders a funscript's stroke-speed heatmap as a fixed-height horizontal bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions: list[dict] = []
        self.setFixedHeight(_STRIP_HEIGHT)

    def set_actions(self, actions) -> None:
        """Show ``actions`` as a heatmap; an empty list paints the inert bar."""
        self._actions = list(actions or [])
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(0, _STRIP_HEIGHT)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        width, height = self.width(), self.height()
        # One heatmap bucket per pixel column, so the strip is as detailed as it's wide.
        colors = heatmap_colors(self._actions, width)
        if not colors:
            painter.fillRect(0, 0, width, height, _EMPTY)
            return
        for x, (r, g, b) in enumerate(colors):
            painter.fillRect(x, 0, 1, height, QColor(r, g, b))
