from __future__ import annotations

import logging
import threading

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)

_in_flight = set()


class _Result(QObject):
    ready = Signal(object)


class _Task(QRunnable):
    def __init__(self, work, result: _Result):
        super().__init__()
        self._work = work
        self._result = result

    def run(self) -> None:
        try:
            value = self._work()
        except Exception:
            logger.warning("Off-thread call failed", exc_info=True)
            value = None
        try:
            self._result.ready.emit(value)
        except RuntimeError:
            logger.info("An off-thread answer came back after the app let go of it")


def run_off_thread(work, done, *, owner: QObject, waits_long: bool = False) -> None:
    result = _Result()
    _in_flight.add(result)

    def deliver(value):
        _in_flight.discard(result)
        if not shiboken6.isValid(owner):
            logger.info("An off-thread answer came back after the %s that asked "
                        "for it was gone", type(owner).__name__)
            return
        done(value)

    result.ready.connect(deliver)
    task = _Task(work, result)
    if waits_long:
        threading.Thread(target=task.run, name="off-thread wait", daemon=True).start()
    else:
        QThreadPool.globalInstance().start(task)
