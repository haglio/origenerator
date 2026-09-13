from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer

from origenerator.fun_time_mode import OFFER_NAME, FunTimeSession, take_the_takeover
from origenerator.win32 import this_process_creation_time

_POLL_MS = 250


class FunTimeOffer(QObject):
    def __init__(self, state_dir: Path, *, take_over: Callable[[FunTimeSession], None],
                 parent: QObject | None = None):
        super().__init__(parent)
        self._state_dir = state_dir
        self._take_over = take_over
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._answer_a_takeover)
        self.renew()

    def renew(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        (self._state_dir / OFFER_NAME).write_text(
            f"{os.getpid()} {this_process_creation_time()}", encoding="utf-8")
        self._timer.start()

    def _answer_a_takeover(self) -> None:
        session = take_the_takeover(self._state_dir, pid=os.getpid())
        if session is None:
            return
        self.withdraw()
        self._take_over(session)

    def withdraw(self) -> None:
        self._timer.stop()
        (self._state_dir / OFFER_NAME).unlink(missing_ok=True)
