from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

from origenerator import alert
from origenerator.comfyui_api import ForeignQueue
from origenerator.gui.asked_at_the_cursor import asked_at
from origenerator.gui.inflight import (
    CANCEL_ALL_BELOW_TEXT,
    CANCEL_ALL_TEXT,
    cancel_all_question,
    cancel_below_question,
    clear_queue_tooltip,
    jobs_below,
    jobs_to_cancel,
)
from origenerator.gui.job_queue_view import JobQueueView

logger = logging.getLogger(__name__)


def read_foreign_queue(client) -> ForeignQueue | None:
    if client is None:
        return None
    try:
        return client.foreign_queue()
    except Exception as e:
        logger.debug("Could not read ComfyUI's queue: %s", e)
        return ForeignQueue(running=[], pending=[])


class ShownJobQueue(QObject):
    changed = Signal(object, int)

    def __init__(self, jobs, client, *, starting, in_flight: Callable[..., list],
                 listed: Callable[[], tuple[list, list]], asks_over: QWidget,
                 cursor: Callable[[], QPoint] = QCursor.pos) -> None:
        super().__init__(asks_over)
        self._jobs = jobs
        self._client = client
        self._starting = starting
        self._in_flight = in_flight
        self._listed = listed
        self._asks_over = asks_over
        self._cursor = cursor
        self._foreign = ForeignQueue(running=[], pending=[])
        self.view = JobQueueView()
        self.view.move_requested.connect(jobs.move)
        self.view.clear_queue_requested.connect(self.clear_foreign)
        self.view.start_now_requested.connect(self.start_now)
        self.view.cancel_all_requested.connect(self.cancel_all)
        self.view.cancel_below_requested.connect(self.cancel_below)
        jobs.reordered.connect(self.update)
        starting.changed.connect(self.update)

    def items(self, rows=None, requests=None) -> list:
        return [self._redrawn_on_cancel(item) for item in self._starting.placed_among(
            self._in_flight(rows=rows, requests=requests), self._jobs)]

    def _redrawn_on_cancel(self, item):
        if item.cancel is None:
            return item

        def cancel_and_redraw(cancel=item.cancel):
            cancel()
            self.update()
        return replace(item, cancel=cancel_and_redraw)

    def now(self) -> tuple[list, int]:
        rows, requests = self._listed()
        holds_every_job = {row["prompt_id"] for row in rows} >= set(self._jobs.queue_order)
        items = self.items(rows=rows, requests=requests) if holds_every_job else self.items()
        return items, self._foreign.total

    def update(self, items=None) -> None:
        items = self.items() if items is None else items
        self.view.set_items(items, self._foreign.total)
        self.changed.emit(items, self._foreign.total)

    def take_foreign(self, queue: ForeignQueue | None) -> None:
        if queue is not None:
            self._foreign = queue

    def start_now(self) -> None:
        self._jobs.start_now()
        self.update()

    def cancel_all(self, over: QWidget | None = None) -> None:
        items = jobs_to_cancel(self.items())
        self._cancel_once_asked(items, CANCEL_ALL_TEXT, cancel_all_question(len(items)), over)

    def cancel_below(self, key: str, over: QWidget | None = None) -> None:
        items = jobs_below(self.items(), key)
        self._cancel_once_asked(items, CANCEL_ALL_BELOW_TEXT,
                                cancel_below_question(len(items)), over)

    def _cancel_once_asked(self, items: list, title: str, question: str,
                           over: QWidget | None) -> None:
        if not items or not self._confirmed(title, question, over):
            return
        for item in reversed(items):
            item.cancel()

    def clear_foreign(self) -> None:
        if self._client is None:
            return
        total = self._foreign.total
        if not total or not self.confirm_clear(total):
            return
        try:
            dropped = self._client.clear_foreign_queue()
        except Exception as e:
            logger.exception("Failed to clear ComfyUI's queue")
            alert.error(
                "Could not clear the queue",
                f"ComfyUI would not drop the other app's jobs:\n\n{e}",
            )
            return
        logger.info("Dropped %d job(s) another app had queued on ComfyUI", dropped)
        self.take_foreign(read_foreign_queue(self._client))
        self.update()

    def confirm_clear(self, total: int) -> bool:
        return self._confirmed(
            "Clear ComfyUI's queue",
            f"{clear_queue_tooltip(total)}?\n\nAnything you queued from here is left alone;"
            " one of theirs already running is interrupted.")

    def _confirmed(self, title: str, question: str, over: QWidget | None = None) -> bool:
        return asked_at(self._cursor(), over or self._asks_over, title, question)
