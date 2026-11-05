from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app_support.win32 import release_mutex, try_acquire_mutex

LOOK_EVERY_S = 0.1
WAIT_S = 60.0


class Turn:
    def __init__(self, name: str, *, wait_s: float = WAIT_S,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._name, self._wait_s, self._sleep, self._clock = name, wait_s, sleep, clock

    @contextmanager
    def taken(self) -> Iterator[bool]:
        held = self._held_once_it_is_free()
        try:
            yield held is not None
        finally:
            if held is not None:
                release_mutex(held)

    def _held_once_it_is_free(self) -> int | None:
        give_up_at = self._clock() + self._wait_s
        while (held := try_acquire_mutex(self._name)) is None and self._clock() < give_up_at:
            self._sleep(LOOK_EVERY_S)
        return held
