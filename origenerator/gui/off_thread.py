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

Queued is what makes the carrier's lifetime the whole problem here: between the
pool thread's emit and the delivery a turn later, anything that frees the
handler leaves Qt to call a function that no longer exists. See
:func:`run_off_thread`.
"""

import logging

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)

# Every carrier still waiting for its answer. Touched only on the thread that
# calls run_off_thread, since that is also the thread the result is delivered on.
_in_flight = set()


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

    ``done`` is called exactly once, with ``None`` when ``work`` raised.

    The carrier is held in :data:`_in_flight` until it delivers, which is the
    whole of what keeps it and its handler alive. It used to rely on being a
    reference *cycle* instead -- the handler closed over the carrier, and the
    carrier's own connection held the handler -- and a cycle nothing outside
    points at is precisely what Python's cyclic collector takes. Collected
    mid-flight, the handler was freed while the pool thread's emit was still
    queued; the queued call then arrived at a function object that had been
    freed and its memory reused. That is not an exception. It is an access
    violation inside the interpreter's own frame setup, no traceback, the
    process simply gone -- and once the 1.5 s poll started running two of these
    per tick it was a crash every few minutes (2026-09-03/04, seven of them
    across the live app and four branch previews, all faulting on the same
    instruction: the free-variable copy at the entry of a closure, reached
    through a queued Qt metacall).
    """
    result = _Result()
    _in_flight.add(result)

    def deliver(value):
        _in_flight.discard(result)  # its last turn; the carrier can go now
        done(value)

    result.ready.connect(deliver)
    QThreadPool.globalInstance().start(_Task(work, result))
