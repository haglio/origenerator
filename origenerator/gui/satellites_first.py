from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

LONGEST_WAIT_MS = 10_000
_LOOK_EVERY_MS = 100


class SatellitesFirst(QObject):
    def __init__(self, parent: QObject, *, served: Callable[[], bool],
                 wait_ms: int = LONGEST_WAIT_MS) -> None:
        super().__init__(parent)
        self._served = served
        self._gives_up_at = time.monotonic() + wait_ms / 1000
        self._waiting: list[Callable[[], None]] = []
        self.over = False
        self._look = QTimer(self)
        self._look.setInterval(_LOOK_EVERY_MS)
        self._look.timeout.connect(self._run_what_waits_if_served)
        self._look.start()

    def then(self, run: Callable[[], None]) -> None:
        if self.over:
            run()
        else:
            self._waiting.append(run)

    def _run_what_waits_if_served(self) -> None:
        if not (self._served() or time.monotonic() >= self._gives_up_at):
            return
        self._look.stop()
        self.over = True
        waiting, self._waiting = self._waiting, []
        for run in waiting:
            run()
