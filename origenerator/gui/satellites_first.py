from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QTimer

from origenerator.gui.deferred import defer

LONGEST_WAIT_S = 10.0
_LOOK_EVERY_MS = 100


class SatellitesFirst(QObject):
    def __init__(self, parent: QObject, *, served: Callable[[], bool],
                 now: Callable[[], float] = time.monotonic,
                 later: Callable[[Callable[[], None]], None] | None = None) -> None:
        super().__init__(parent)
        self._served = served
        self._now = now
        self._later = later or partial(defer, self)
        self._gives_up_at = now() + LONGEST_WAIT_S
        self._waiting: deque[tuple[Callable, bool]] = deque()
        self._handed_off = False
        self.over = False
        self._timer = QTimer(self)
        self._timer.setInterval(_LOOK_EVERY_MS)
        self._timer.timeout.connect(self.look)
        self._timer.start()

    def then(self, run: Callable[[], None]) -> None:
        self._add(run, hands_off=False)

    def then_after(self, run: Callable[[Callable[[], None]], None]) -> None:
        self._add(run, hands_off=True)

    def _add(self, run, *, hands_off: bool) -> None:
        if self.over and not self._waiting and not self._handed_off:
            self._run(run, hands_off=hands_off)
        else:
            self._waiting.append((run, hands_off))

    def look(self) -> None:
        if self.over or not (self._served() or self._now() >= self._gives_up_at):
            return
        self._timer.stop()
        self.over = True
        self._run_the_next()

    def _run_the_next(self) -> None:
        if self._waiting:
            run, hands_off = self._waiting.popleft()
            self._run(run, hands_off=hands_off)

    def _run(self, run, *, hands_off: bool) -> None:
        if hands_off:
            self._handed_off = True
            run(self._done_with_what_was_handed_off)
            return
        if self._waiting:
            self._later(self._run_the_next)
        run()

    def _done_with_what_was_handed_off(self) -> None:
        self._handed_off = False
        self._later(self._run_the_next)
