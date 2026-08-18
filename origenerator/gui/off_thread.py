"""Run one slow call off the UI thread and hand its result back on it.

The gallery's recipe match asks a local model which past recipe fits a dropped
image. That is an HTTP round trip to a model that thinks for several seconds, and
run inline it froze the whole window for exactly as long — most visibly on the
spoken "genau it", where the window is a fullscreen picture and the freeze is all
there is to look at.

Deliberately tiny: a callable to run and a callable to hand the result to. Qt's
global pool does the running, and the result crosses back through a queued signal,
so ``done`` runs on the thread that called this — free to touch widgets, the
database, and everything else the caller owns.
"""

import logging

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)


class _Result(QObject):
    """Carries one finished call back to the thread that asked for it."""

    ready = pyqtSignal(object)


class _Task(QRunnable):
    def __init__(self, work, result: _Result):
        super().__init__()
        self._work = work
        self._result = result

    def run(self) -> None:
        try:
            value = self._work()
        except Exception:
            # A failure is a result like any other: the caller's own fallback
            # decides what no answer means, and a raised exception on a pool
            # thread would simply be lost.
            logger.warning("Off-thread call failed", exc_info=True)
            value = None
        self._result.ready.emit(value)


def run_off_thread(work, done) -> None:
    """Call ``work()`` on the global pool, then ``done(result)`` back on this thread.

    ``done`` is called exactly once, with ``None`` when ``work`` raised. The
    carrier keeps itself alive by parenting nothing and being closed over by its
    own handler, which is released when the connection is torn down after firing.
    """
    result = _Result()

    def deliver(value):
        result.ready.disconnect(deliver)  # release the carrier and this closure
        done(value)

    result.ready.connect(deliver)
    QThreadPool.globalInstance().start(_Task(work, result))
