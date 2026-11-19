from __future__ import annotations

import time


class Playhead:
    def __init__(self, player, *, clock=time.monotonic) -> None:
        self._player = player
        self._clock = clock
        self._held: tuple[int, float | None] | None = None

    @property
    def held(self) -> bool:
        return self._held is not None

    def position(self) -> int:
        if self._held is None:
            return int(self._player.position())
        at, since = self._held
        if since is None:
            return at
        ran = at + round((self._clock() - since) * 1000)
        length = int(self._player.duration() or 0)
        return ran % length if length > 0 else ran

    def hold(self) -> None:
        self._held = int(self._player.position()), None

    def run(self, running: bool) -> None:
        if self._held is None or running == (self._held[1] is not None):
            return
        self._held = (self._held[0], self._clock()) if running else (self.position(), None)

    def release(self) -> int:
        at = self.position()
        self._held = None
        return at

    def forget(self) -> None:
        self._held = None
