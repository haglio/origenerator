from __future__ import annotations

from funestra.scrub import Scrub
from funestra.scrubber_bar import (
    BAR_INSET_Y,
    SCRUBBER_HEIGHT,
    TrackMarks,
    progress_bar_bgra,
    time_at_x,
)
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from origenerator.funscript import heatmap_colors

_FLOAT_OFF_EVERY_EDGE = BAR_INSET_Y


class Scrubber(QWidget):
    scrubbed = Signal(int)
    held = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions: list[dict] = []
        self._position: int | None = None
        self._duration = 0
        self._scrub = Scrub(seek=self._go_to, hold=self.held.emit)
        self.setFixedHeight(SCRUBBER_HEIGHT)

    def set_actions(self, actions) -> None:
        self._actions = list(actions or [])
        self._position = None
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        self._duration = int(duration_ms or 0)
        self.update()

    def set_position(self, position_ms: int | None) -> None:
        self._position = position_ms
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._duration <= 0:
            super().mousePressEvent(event)
            return
        self._scrub.press(self._time_at(event.position().x()))

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._scrub.drag(self._time_at(event.position().x()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._scrub.release()

    def _time_at(self, x: float) -> float:
        return time_at_x(x, self._duration, *self._track_x())

    def _go_to(self, ms: float) -> None:
        moment = round(ms)
        self.set_position(moment)
        self.scrubbed.emit(moment)

    def _track_x(self) -> tuple[int, int]:
        return _FLOAT_OFF_EVERY_EDGE, self.width() - _FLOAT_OFF_EVERY_EDGE

    def sizeHint(self) -> QSize:
        return QSize(0, SCRUBBER_HEIGHT)

    def paintEvent(self, event) -> None:
        x0, x1 = self._track_x()
        if x1 - x0 < 2 * _FLOAT_OFF_EVERY_EDGE:
            return
        position = None if self._duration <= 0 or self._position is None else min(
            self._position, self._duration)
        bar = progress_bar_bgra(TrackMarks(position, self._duration), self.width(), self.height(),
                                heatmap=heatmap_colors(self._actions, buckets=x1 - x0) or None,
                                track=(x0, x1), opaque=True)
        image = QImage(bar.data, bar.shape[1], bar.shape[0], bar.strides[0], QImage.Format.Format_ARGB32)
        QPainter(self).drawImage(0, 0, image)
