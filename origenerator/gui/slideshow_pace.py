"""How long a slide stays up — one number, app-wide.

Genau's console carries a clip-seconds pair, and here the clips are the slides,
so that pair sets this. It is app-wide rather than per-slideshow because the
console is: the same one is on the main window, the fullscreen viewer and both
slideshows, and a pace that meant something different on each would read as four
paces. Set it in the main window with nothing playing and the next slideshow
opens at it; set it while one is running and that one changes pace under you.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS

# The console's pair steps by this, and will not walk past these ends.
STEP_S = 1
MIN_S, MAX_S = 1, 60


class SlideshowPace(QObject):
    """The seconds an unheld slide holds the screen, and word when it changes."""

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


class PaceOnlyHost:
    """What the console acts on where there is no slideshow behind it.

    The main window and the plain fullscreen viewer show the console with
    nothing to step, so its transport does nothing there — but the pace is
    app-wide and setting it is worth doing anywhere, because it is what the next
    slideshow will open at.
    """

    locked = True

    def __init__(self, pace: SlideshowPace):
        self._pace = pace

    @property
    def dwell_s(self) -> int:
        return self._pace.seconds

    def set_dwell_s(self, seconds: int) -> None:
        self._pace.set_seconds(seconds)

    def stroke_step(self, delta: int) -> None: ...

    def stroke_toggle_hold(self) -> None: ...

    def stroke_cull(self) -> None: ...
