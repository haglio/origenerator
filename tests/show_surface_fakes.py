"""A stand-in for the players' engine, for the show's surface to drive.

Mirrors what :class:`player_core.render_player.MpvRenderPlayer` offers a host
that owns the window: a file to open, the pace a picture holds for, the freeze,
the sound, the creep into a still, and the two things a host has to ask about
what happened -- whether the item ran out and whether anything opened at all.
"""
from __future__ import annotations

from pathlib import Path


class FakeEngine:
    def __init__(self) -> None:
        self.loaded: list[Path] = []
        self.pace: float | None = None
        self.paused: bool | None = None
        self.muted = True
        self.eof = False
        self.idle = False
        self.video_dims = (0, 0)
        self.pushes = 0
        self.closed = False
        self.stopped = False
        self.position_ms = 0.0

    def load(self, path) -> None:
        self.loaded.append(Path(path))
        self.eof = False
        self.idle = False
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def set_pace(self, seconds: float) -> None:
        self.pace = seconds

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def push_still(self) -> None:
        self.pushes += 1

    def close(self) -> None:
        self.closed = True
