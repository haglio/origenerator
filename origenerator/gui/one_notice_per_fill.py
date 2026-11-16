from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager


class OneNoticePerFill:
    def __init__(self, notify: Callable[[], object]) -> None:
        self._notify = notify
        self._filling = 0
        self._held = False

    def changed(self, *_said) -> None:
        if self._filling:
            self._held = True
            return
        self._notify()

    @contextmanager
    def filling(self) -> Iterator[None]:
        self._filling += 1
        try:
            yield
        finally:
            self._filling -= 1
        if not self._filling and self._held:
            self._held = False
            self._notify()
