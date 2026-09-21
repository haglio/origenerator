from __future__ import annotations

from player_core.timeline import (
    BAR_BORDER,
    BAR_EDGE,
    BAR_FILL,
    BAR_INSET_Y,
    BORDER_W,
    CURSOR,
    CURSOR_W,
    TIMELINE_HEIGHT,
    bar_x,
)
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from origenerator.funscript import heatmap_colors


def _at_full_strength(player_color) -> QColor:
    return QColor(*player_color[:3])


_FILL = _at_full_strength(BAR_FILL)
_BORDER = _at_full_strength(BAR_BORDER)
_EDGE = _at_full_strength(BAR_EDGE)
_CURSOR = _at_full_strength(CURSOR)
_FLOAT_OFF_EVERY_EDGE = BAR_INSET_Y


class VideoTimeline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions: list[dict] = []
        self._position: int | None = None
        self._duration = 0
        self.setFixedHeight(TIMELINE_HEIGHT)

    def set_actions(self, actions) -> None:
        self._actions = list(actions or [])
        self._position = None
        self._duration = 0
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        self._duration = int(duration_ms or 0)
        self.update()

    def set_position(self, position_ms: int | None) -> None:
        self._position = position_ms
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(0, TIMELINE_HEIGHT)

    def paintEvent(self, event) -> None:
        x0, x1 = _FLOAT_OFF_EVERY_EDGE, self.width() - _FLOAT_OFF_EVERY_EDGE
        y0, y1 = _FLOAT_OFF_EVERY_EDGE, self.height() - _FLOAT_OFF_EVERY_EDGE
        if _too_narrow_for_a_track(x1 - x0, y1 - y0):
            return
        painter = QPainter(self)
        self._paint_fill(painter, x0, x1, y0, y1)
        self._paint_frame(painter, x0, x1, y0, y1)
        self._paint_cursor(painter, x0, x1, y0, y1)

    def _paint_fill(self, painter, x0, x1, y0, y1) -> None:
        motion = heatmap_colors(self._actions, buckets=x1 - x0)
        if not motion:
            painter.fillRect(x0, y0, x1 - x0, y1 - y0, _FILL)
            return
        for column, (red, green, blue) in enumerate(motion):
            painter.fillRect(x0 + column, y0, 1, y1 - y0, QColor(red, green, blue))

    def _paint_frame(self, painter, x0, x1, y0, y1) -> None:
        _ring(painter, x0, x1, y0, y1, 1, _EDGE)
        _ring(painter, x0 + 1, x1 - 1, y0 + 1, y1 - 1, BORDER_W - 1, _BORDER)

    def _paint_cursor(self, painter, x0, x1, y0, y1) -> None:
        if self._position is None or self._duration <= 0:
            return
        center = bar_x(min(self._position, self._duration), self._duration, x0, x1)
        left = min(max(x0, center - CURSOR_W // 2), x1 - CURSOR_W)
        painter.fillRect(left, y0, CURSOR_W, y1 - y0, _CURSOR)


def _too_narrow_for_a_track(width, height) -> bool:
    return width < 2 * BORDER_W or height < 2 * BORDER_W


def _ring(painter, x0, x1, y0, y1, thickness, color) -> None:
    painter.fillRect(x0, y0, x1 - x0, thickness, color)
    painter.fillRect(x0, y1 - thickness, x1 - x0, thickness, color)
    painter.fillRect(x0, y0, thickness, y1 - y0, color)
    painter.fillRect(x1 - thickness, y0, thickness, y1 - y0, color)
