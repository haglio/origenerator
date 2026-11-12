from __future__ import annotations

from PySide6.QtCore import QObject, Signal

STEP_S = 1
MIN_S, MAX_S = 1, 60
DEFAULT_S = 4


class SlideshowPace(QObject):
    changed = Signal(int)

    def __init__(self, seconds: int = DEFAULT_S, parent=None):
        super().__init__(parent)
        self._seconds = self._clamped(seconds)

    @property
    def seconds(self) -> int:
        return self._seconds

    def set_seconds(self, seconds: int) -> None:
        seconds = self._clamped(seconds)
        if seconds != self._seconds:
            self._seconds = seconds
            self.changed.emit(seconds)

    def step(self, delta: int) -> None:
        self.set_seconds(self._seconds + delta)

    @staticmethod
    def _clamped(seconds: int) -> int:
        return max(MIN_S, min(MAX_S, int(seconds)))
