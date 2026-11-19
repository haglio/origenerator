from __future__ import annotations

import logging
import threading

from origenerator.gui.off_thread import run_off_thread

logger = logging.getLogger(__name__)


class Errand:
    def __init__(self, work, answered):
        self._work = work
        self._answered = answered
        self._done = threading.Event()
        self._told = False
        self.value = None
        self.error: Exception | None = None

    def send(self, *, owner, run=run_off_thread, **how) -> Errand:
        run(self._do, self._tell, owner=owner, **how)
        return self

    def _do(self) -> None:
        try:
            self.value = self._work()
        except Exception as e:
            logger.warning("An errand off the window's thread failed", exc_info=True)
            self.error = e
        finally:
            self._done.set()

    def _tell(self, _nothing=None) -> None:
        if self._told:
            return
        self._told = True
        self._answered(self)

    def wait(self) -> None:
        self._done.wait()

    def settle(self) -> None:
        self._done.wait()
        self._tell()
