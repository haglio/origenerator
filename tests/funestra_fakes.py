"""A stand-in for the players' engine, for a Funestra in this app's window to run on.

What :class:`player_core.mpv_player.MpvPlayer` offers a Funestra, answered
from memory: the file it was handed, the one staged after it, the pace, the
freeze, the sound, a still's move, and the overlays the panel and a picture
are composited with.
"""
from __future__ import annotations

from pathlib import Path


class FakePlayer:
    def __init__(self, *, duration_ms: float = 5_000.0) -> None:
        self.opened: list[Path] = []
        self.playlist: list[Path] = []
        self.playlist_pos = 0
        self.duration_ms = duration_ms
        self.position_ms = 0.0
        self.frame_rate = 25.0
        self.paused = False
        self.loop_file = False
        self.closed = False
        self.overlays: dict[int, tuple[int, int, object]] = {}
        self.volume = 100
        self.muted = False
        self.seeks: list[float] = []
        self.speed = 1.0
        self.pace_s: float | None = None
        self.showing_picture = False
        self.source_dims = (0, 0)
        self.ab_loop: tuple[float, float] | None = None
        self.pushes = 0
        self.swapped: list[Path] = []
        self.screenshot = None
        self.idle = False
        self.stopped = False

    def tile_to_fill(self, window_width: int, window_height: int) -> None:
        pass

    def load(self, path: Path) -> None:
        self.opened.append(path)
        self.playlist = [path]
        self.playlist_pos = 0
        self.position_ms = 0.0
        self.idle = False
        self.stopped = False

    def swap_still(self, path: Path) -> None:
        self.swapped.append(path)
        self.playlist[self.playlist_pos] = path

    def stop(self) -> None:
        self.stopped = True
        self.idle = True

    def stage_next(self, path: Path) -> None:
        del self.playlist[self.playlist_pos + 1:]
        self.playlist.append(path)

    def clear_next(self) -> None:
        del self.playlist[self.playlist_pos + 1:]

    @property
    def advanced_to_next(self) -> bool:
        return self.playlist_pos >= 1

    def drop_consumed(self) -> None:
        while self.playlist_pos > 0:
            self.playlist.pop(0)
            self.playlist_pos -= 1

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_loop_file(self, loop: bool) -> None:
        self.loop_file = loop

    def set_pace(self, seconds: float) -> None:
        self.pace_s = seconds

    def push_still(self) -> None:
        self.pushes += 1

    def seek_ms(self, ms: float) -> None:
        self.seeks.append(ms)
        self.position_ms = max(0.0, min(self.duration_ms, ms))

    def set_ab_loop(self, in_ms: float, out_ms: float) -> None:
        self.ab_loop = (in_ms, out_ms)

    def clear_ab_loop(self) -> None:
        self.ab_loop = None

    def set_volume(self, volume: int) -> None:
        self.volume = volume

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def close(self) -> None:
        self.closed = True

    def screenshot_bgra(self):
        return self.screenshot

    def overlay(self, ident: int, x: int, y: int, bgra) -> None:
        self.overlays[ident] = (x, y, bgra)

    def remove_overlay(self, ident: int) -> None:
        self.overlays.pop(ident, None)

    def run_out(self) -> None:
        """The item on screen ended: a clip played through, or a picture's
        pace ran out.  The engine rolls onto what was staged after it, where
        something was."""
        if len(self.playlist) > self.playlist_pos + 1:
            self.playlist_pos += 1

    @property
    def on_screen(self) -> Path | None:
        return self.playlist[self.playlist_pos] if self.playlist else None

    @property
    def staged_next(self) -> Path | None:
        tail = self.playlist[self.playlist_pos + 1:]
        return tail[0] if tail else None
