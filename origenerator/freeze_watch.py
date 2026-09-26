from __future__ import annotations

import faulthandler
import logging
import time
from datetime import datetime

from PyQt6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

STALLED_AFTER_S = 10.0
BEAT_MS = 1000


class FreezeWatch(QObject):
    def __init__(self, crash_log, *, stalled_after_s: float = STALLED_AFTER_S,
                 beat_ms: int = BEAT_MS, clock=time.monotonic,
                 arm=faulthandler.dump_traceback_later,
                 disarm=faulthandler.cancel_dump_traceback_later, parent=None) -> None:
        super().__init__(parent)
        self._crash_log = crash_log
        self._stalled_after_s = stalled_after_s
        self._clock = clock
        self._arm = arm
        self._disarm = disarm
        self._last_beat = clock()
        self._beats = QTimer(self)
        self._beats.timeout.connect(self.beat)
        self._beats.start(beat_ms)
        self._rearm()

    def beat(self) -> None:
        now = self._clock()
        stalled_for = now - self._last_beat
        self._last_beat = now
        if stalled_for >= self._stalled_after_s:
            self._say_the_window_answers_again(stalled_for)
        self._rearm()

    def stop(self) -> None:
        self._beats.stop()
        self._disarm()

    def _rearm(self) -> None:
        self._arm(self._stalled_after_s, repeat=False, file=self._crash_log, exit=False)

    def _say_the_window_answers_again(self, stalled_for: float) -> None:
        logger.warning("The window stopped answering for %.0f s; every thread's stack "
                       "from %.0f s in is in origenerator_crash.log",
                       stalled_for, self._stalled_after_s)
        answered_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._crash_log.write(f"=== answering again after {stalled_for:.0f} s, "
                              f"at {answered_at} ===\n")
        self._crash_log.flush()
