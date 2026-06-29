"""Serialize generation jobs across the Generate subtabs, one at a time.

ComfyUI runs prompts sequentially on a single pipeline, so submitting several at
once just hides the wait. Instead this queue holds back-to-back Generate clicks
and releases them one by one, letting each waiting panel show its place in line
and a countdown to its turn. The countdown math (``pending_etas``) is a pure
function so it can be unit-tested without Qt or a clock.
"""

import time
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject, QTimer

from origenerator.timing import estimate_seconds


def pending_etas(running_remaining: float, pending_estimates: list[float]) -> list[float]:
    """Seconds until each waiting job starts.

    The first waiting job starts once the running job's ``running_remaining`` is
    up; each later job also waits out the estimates of the jobs ahead of it.
    Negative inputs are clamped to zero so a job that overran its estimate never
    pushes an ETA backwards.
    """
    etas: list[float] = []
    cumulative = max(0.0, running_remaining)
    for estimate in pending_estimates:
        etas.append(cumulative)
        cumulative += max(0.0, estimate)
    return etas


@dataclass
class _Slot:
    panel: Any
    workflow_name: str
    started: float | None = None


class JobQueue(QObject):
    """Runs one generation at a time across the Generate subtabs.

    A panel ``submit``s when its Generate is clicked. The head of the line runs
    immediately (``panel.run_now()``); the rest wait, each told its 1-based
    ``position`` and a live ETA via ``panel.set_queue_status(position, eta)``.
    The running panel calls ``release`` when its job ends (or ``cancel`` if its
    tab closes) to let the next start.
    """

    def __init__(self, db, clock=time.monotonic, parent=None):
        super().__init__(parent)
        self._db = db
        self._clock = clock
        self._running: _Slot | None = None
        self._pending: list[_Slot] = []
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)

    def submit(self, panel, workflow_name: str):
        self._pending.append(_Slot(panel, workflow_name))
        self._start_next_if_idle()
        self._refresh()

    def release(self, panel):
        """The running job finished — start the next in line."""
        if self._running is not None and self._running.panel is panel:
            self._running = None
            self._start_next_if_idle()
        self._refresh()

    def cancel(self, panel):
        """A subtab closed — drop its slot, advancing the queue if it was running."""
        if self._running is not None and self._running.panel is panel:
            self._running = None
            self._start_next_if_idle()
        else:
            self._pending = [s for s in self._pending if s.panel is not panel]
        self._refresh()

    def _start_next_if_idle(self):
        if self._running is None and self._pending:
            self._running = self._pending.pop(0)
            self._running.started = self._clock()
            self._running.panel.run_now()

    def _refresh(self):
        running_remaining = 0.0
        if self._running is not None:
            estimate = self._estimate(self._running.workflow_name)
            started = self._running.started
            elapsed = self._clock() - started if started is not None else 0.0
            running_remaining = max(0.0, estimate - elapsed)
        estimates = [self._estimate(s.workflow_name) for s in self._pending]
        for position, (slot, eta) in enumerate(
            zip(self._pending, pending_etas(running_remaining, estimates)), start=1
        ):
            slot.panel.set_queue_status(position, eta)
        if self._pending and not self._timer.isActive():
            self._timer.start()
        elif not self._pending:
            self._timer.stop()

    def _estimate(self, workflow_name: str) -> float:
        return estimate_seconds(self._db.recent_durations(workflow_name)) or 0.0
