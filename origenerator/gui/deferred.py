"""Run something on the next turn of the event loop, owned by whoever asked.

``QTimer.singleShot(0, a_lambda)`` reads like exactly this and is not. PyQt has
to wrap a plain callable in a proxy QObject of its own, parented to nothing, and
the call reaches that proxy as a posted event. Neither the proxy nor the
callable is tied to the widget that asked for the wait, so a redraw between the
post and the delivery can free the callable while its event is still in the
queue.

What that costs is not an exception. Calling a function object that has been
freed lands in the interpreter's own frame setup, reading the freed function's
closure out of reused memory -- an access violation, no traceback, the process
simply gone. Seven of those on 2026-09-03/04 all faulted on the same
instruction: the free-variable copy at the entry of a closure, reached from a
queued Qt metacall through PyQt's slot proxy, which is this shape and no other.

:func:`defer` gives the wait an owner. The timer is parented to the object that
asked, holds the callable itself, and calls a bound method of that same timer --
so destroying the owner destroys the timer, and a destroyed QTimer takes its own
pending event with it. The work runs while its owner is alive, or not at all.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer


class _DeferredCall(QTimer):
    """One pending piece of work, alive exactly as long as it may still run."""

    def __init__(self, owner: QObject, work: Callable[[], None]):
        super().__init__(owner)   # the parent owns it; no free-floating proxy
        self._work = work         # ...and the work is held here, not by PyQt
        self.setSingleShot(True)
        self.timeout.connect(self._fire)
        self.start(0)

    def _fire(self) -> None:
        work, self._work = self._work, None   # never twice, whatever work does
        self.deleteLater()
        if work is not None:
            work()


def defer(owner: QObject, work: Callable[[], None]) -> None:
    """Run ``work`` on the next turn of the event loop, if ``owner`` is still there.

    For the second half of anything that has to wait for a layout: the pane was
    drawn this turn but has no real geometry until Qt has laid it out, so the
    scroll or the reveal that aims at it has to aim again afterwards.
    """
    _DeferredCall(owner, work)
