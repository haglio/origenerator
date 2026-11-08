from __future__ import annotations

from typing import NamedTuple


class ForTheSetter(NamedTuple):
    text: str


class OpenSetters:
    def __init__(self):
        self._open: list = []

    def hold(self, window) -> None:
        self._open.append(window)
        window.closed.connect(lambda window=window: self._let_go(window))

    def _let_go(self, window) -> None:
        self._open = [held for held in self._open if held is not window]

    def _in_front(self):
        return next((window for window in self._open if window.isActiveWindow()), None)

    def knows(self, text: str) -> bool:
        front = self._in_front()
        return front is not None and front.knows(text)

    def hear(self, text: str) -> bool:
        front = self._in_front()
        return front is not None and front.hear(text)
