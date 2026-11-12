from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from shared_ui import running_copy

from origenerator import app_link

logger = logging.getLogger(__name__)


class LinkListener(QObject):
    def __init__(self, *, checkout: Path, environ=None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._answer: Callable[[str], None] | None = None
        self._waiting: list[str] = []
        self._asked_for(
            (os.environ if environ is None else environ).pop(app_link.CARRIED_IN, ""))
        self._server = running_copy.listen(
            app_link.channel_for(checkout),
            lambda said, _reply: self._asked_for(said.decode("ascii", "replace").strip()))
        if not self._server.isListening():
            logger.warning("Clicks on this app's toasts cannot be answered here: %s",
                           self._server.errorString())

    def answer_with(self, go_to: Callable[[str], None]) -> None:
        self._answer = go_to
        waiting, self._waiting = self._waiting, []
        for generation in waiting:
            go_to(generation)

    def _asked_for(self, generation: str) -> None:
        wanted = app_link.a_generation(generation)
        if wanted is None:
            if generation:
                logger.warning("A click asked for something that is not a generation")
            return
        logger.info("A click on a toast asked for %s", wanted)
        if self._answer is None:
            self._waiting.append(wanted)
        else:
            self._answer(wanted)
