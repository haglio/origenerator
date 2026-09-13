"""The slow push into a still while it holds the screen: how deep it goes, and
where it has got to.

The move itself is drawn on Qt Quick's render thread
(:mod:`origenerator.gui.ken_burns_still`), which never reports back where it is,
so :class:`PushClock` keeps that account on this side from the same starts, pauses
and paces the render thread was given.
"""
from __future__ import annotations

# How much closer the picture is by the time its dwell runs out. Small on
# purpose — the move has to be something you notice having happened rather than
# something you watch happening, and at the standard four-second dwell this is
# already a tenth of the frame in four seconds.
ZOOM_SPAN = 1.10


def zoom_at(progress: float, span: float = ZOOM_SPAN) -> float:
    return 1.0 + (span - 1.0) * max(0.0, min(1.0, progress))


class PushClock:
    def __init__(self):
        self._started_ms = 0.0
        self._dwell_ms = 0
        self._paused_at_ms = 0.0

    def start(self, now_ms: float, dwell_ms: int, progress: float = 0.0) -> None:
        self._started_ms = now_ms - progress * dwell_ms
        self._dwell_ms = dwell_ms

    def pause(self, now_ms: float) -> None:
        self._paused_at_ms = now_ms

    def resume(self, now_ms: float) -> None:
        self._started_ms += now_ms - self._paused_at_ms

    def retime(self, now_ms: float, dwell_ms: int) -> None:
        reached = self.progress(now_ms)
        self._dwell_ms = dwell_ms
        self._started_ms = now_ms - reached * dwell_ms

    def progress(self, now_ms: float) -> float:
        return ((now_ms - self._started_ms) / self._dwell_ms) % 1.0
