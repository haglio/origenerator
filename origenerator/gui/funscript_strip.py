"""A thin funscript heatmap painted under a video preview.

Proof at a glance that a clip has a funscript — and what its motion looks
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
_PLAYHEAD = QColor(255, 255, 255)  # white reads over every heatmap color
_PLAYHEAD_PX = 2


class FunscriptStrip(QWidget):
    """Renders a funscript's travel-speed heatmap as a fixed-height horizontal bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions: list[dict] = []
        self._playhead: int | None = None
        self.setFixedHeight(_STRIP_HEIGHT)

    def set_actions(self, actions) -> None:
        """Show ``actions`` as a heatmap; an empty list paints the inert bar.
        A new script starts with no playhead: playback has not reported yet."""
        self._actions = list(actions or [])
        self._playhead = None
        self.update()

    def set_playhead(self, position_ms: int | None) -> None:
        """Mark how far into the script playback has reached, on the heatmap's
        own time axis (``[0, last action]``), or take the mark away (``None``)."""
        self._playhead = position_ms
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
        end_ms = self._actions[-1]["at"]
        if self._playhead is not None and end_ms > 0:
            x = round(width * min(self._playhead, end_ms) / end_ms)
            painter.fillRect(min(x, width - _PLAYHEAD_PX), 0, _PLAYHEAD_PX, height, _PLAYHEAD)
