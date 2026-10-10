"""How long a slide stays up — one number, app-wide.

Genau's console carries a clip-seconds pair, and here the clips are the slides,
so that pair on a show's panel sets this. It is app-wide rather than
per-slideshow: set it while one is running and that one changes pace under you,
and the next slideshow opens at it.

Nought is a pace like any other here, and it means never: the slide holds the
screen until an arrow moves it. Genau's own floor is one second because a
Genau clip is a fraction of one, but a picture is happy to sit there — and a
picture sitting there is the whole of what double-clicking one now opens, so
nought has to be a number the console can reach.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS

# The console's pair steps by this, and will not walk past these ends.
STEP_S = 1
MIN_S, MAX_S = 0, 60


class SlideshowPace(QObject):
    """The seconds an unlocked slide holds the screen, and word when it changes."""

    changed = pyqtSignal(int)

    def __init__(self, seconds: int = DEFAULT_IMAGE_DWELL_MS // 1000, parent=None):
        super().__init__(parent)
        self._seconds = self._clamped(seconds)

    @property
    def seconds(self) -> int:
        return self._seconds

    @property
    def dwell_ms(self) -> int:
        return self._seconds * 1000

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
