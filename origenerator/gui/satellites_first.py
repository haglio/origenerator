from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

LONGEST_WAIT_S = 10.0
_LOOK_EVERY_MS = 100


class SatellitesFirst(QObject):
    def __init__(self, parent: QObject, *, served: Callable[[], bool],
                 now: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self._served = served
        self._now = now
        self._gives_up_at = now() + LONGEST_WAIT_S
        self._waiting: list[Callable[[], None]] = []
        self.over = False
        self._timer = QTimer(self)
        self._timer.setInterval(_LOOK_EVERY_MS)
        self._timer.timeout.connect(self.look)
        self._timer.start()

    def then(self, run: Callable[[], None]) -> None:
        if self.over:
            run()
        else:
            self._waiting.append(run)

    def look(self) -> None:
        if self.over or not (self._served() or self._now() >= self._gives_up_at):
            return
        self._timer.stop()
        self.over = True
        waiting, self._waiting = self._waiting, []
        for run in waiting:
            run()
