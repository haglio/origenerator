"""Run something on the next turn of the event loop, owned by whoever asked.

QTimer.singleShot(0, a_lambda) wraps the callable in a PyQt proxy parented to nothing, so a redraw
between the post and the delivery can free the callable while its event is queued, and the call then
crashes the process with an access violation and no traceback. Here the timer is a child of the owner and
holds the callable itself: destroying the owner destroys the timer and its pending event.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer


class _DeferredCall(QTimer):
    def __init__(self, owner: QObject, work: Callable[[], None]):
        super().__init__(owner)
        self._work = work
        self.setSingleShot(True)
        self.timeout.connect(self._fire)
        self.start(0)

    def _fire(self) -> None:
        work, self._work = self._work, None
        self.deleteLater()
        if work is not None:
            work()


def defer(owner: QObject, work: Callable[[], None]) -> None:
    _DeferredCall(owner, work)
