"""How long a slide stays up, which a slideshow's Clip seconds row sets.

Standalone keeps one, and the next slideshow opens at it; in a Fun Time session
each Satellite keeps its own, starting at Standalone's.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

# The OSR2 controls' pair steps by this, and will not walk past these ends.
STEP_S = 1
MIN_S, MAX_S = 1, 60
DEFAULT_S = 4


class SlideshowPace(QObject):
    """The seconds an unlocked slide holds the screen, and word when it changes."""

    changed = pyqtSignal(int)

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
