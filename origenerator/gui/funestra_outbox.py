from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

from PySide6.QtCore import QObject

_LIST, _VERBS = "list", "verbs"


class FunestraOutbox(QObject):
    def __init__(self, channel, *, run, lost: Callable[[str], None]) -> None:
        super().__init__()
        self._channel = channel
        self._run = run
        self._lost = lost
        self._waiting: list[tuple[str, list]] = []
        self._writing = False
        self._gathering = 0

    def write_playlist(self, making: Callable[[], list]) -> None:
        self._waiting.append((_LIST, making))
        self._flush()

    def send(self, verb: str) -> None:
        if self._waiting and self._waiting[-1][0] == _VERBS:
            self._waiting[-1][1].append(verb)
        else:
            self._waiting.append((_VERBS, [verb]))
        self._flush()

    @contextmanager
    def gathered(self):
        self._gathering += 1
        try:
            yield
        finally:
            self._gathering -= 1
            self._flush()

    def _flush(self) -> None:
        if self._gathering or self._writing or not self._waiting:
            return
        batch, self._waiting = self._waiting, []
        self._writing = True
        self._run(lambda: self._write(batch), self._written, owner=self)

    def _write(self, batch) -> list[str]:
        lost = []
        for kind, what in batch:
            if kind == _LIST:
                self._channel.write_playlist(what())
            elif not self._channel.send_all(what):
                lost.extend(what)
        return lost

    def _written(self, lost: list[str] | None) -> None:
        self._writing = False
        for verb in lost or ():
            self._lost(verb)
        self._flush()
