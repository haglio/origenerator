"""The one place a Request is asked of the model, spoken or typed: the Job Queue's
line held while the model has the card, the ask off the UI thread, the answer back."""
from __future__ import annotations

import logging

from PyQt6 import sip
from PyQt6.QtCore import QObject

from origenerator import collection_notes, config, graphics_card, prompt_edit
from origenerator.gui.off_thread import run_off_thread

logger = logging.getLogger(__name__)

CARD_DEADLINE_S = 600.0  # how long a Request waits for ComfyUI before the rules answer alone
HOLDER = "Origenerator's Request"  # what the card's claim says while the model answers one


class RequestAnswerer(QObject):
    def __init__(self, db, jobs, client, *, notes_path=None, work_out=None,
                 wait_for_the_card=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._jobs = jobs
        self._client = client
        self._notes_path = notes_path or config.COLLECTION_NOTES_PATH
        self._work_out = work_out or prompt_edit.work_out
        self._wait_for_the_card = wait_for_the_card or graphics_card.wait_for_the_card

    def ask(self, about: str | None, positive: str, negative: str, words: str, *,
            owner: QObject, then) -> None:
        exchange = self._db.exchange_of(about) if about else []
        if self._jobs is not None:
            self._jobs.hold_for_the_model()
        run_off_thread(lambda: self._answer(positive, negative, words, exchange),
                       lambda revision: self._deliver(owner, then, revision),
                       owner=self, waits_long=True)

    def _answer(self, positive: str, negative: str, words: str, exchange):
        try:
            if (self._client is not None
                    and not self._wait_for_the_card(self._client, HOLDER,
                                                    deadline_s=CARD_DEADLINE_S)):
                return prompt_edit.apply_request(positive, negative, words)
            examples = prompt_edit.prompts_touching(
                words, reversed(self._db.distinct_positive_prompts()))
            return self._work_out(positive, negative, words, exchange=exchange,
                                  notes=collection_notes.read(self._notes_path),
                                  examples=examples)
        except Exception as exc:  # noqa: BLE001 -- answered with nothing, never raised off-thread
            logger.warning("Could not work out a request (%s)", type(exc).__name__)
            return None
        finally:
            graphics_card.let_go_of_the_card()

    def _deliver(self, owner: QObject, then, revision) -> None:
        if self._jobs is not None:
            self._jobs.the_model_let_go()
        if sip.isdeleted(owner):
            logger.info("A request's answer came back after what asked for it was gone")
            return
        then(revision)
