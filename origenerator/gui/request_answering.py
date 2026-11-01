from __future__ import annotations

import logging

from PyQt6 import sip
from PyQt6.QtCore import QObject

from origenerator import collection_notes, config, graphics_card, prompt_edit
from origenerator.gui.off_thread import run_off_thread

logger = logging.getLogger(__name__)

GRAPHICS_CARD_DEADLINE_S = 600.0
HOLDER = "Origenerator's Request"


def _exchange_of(db, about: str | None) -> list:
    return db.requests.exchange_of(about) if about else []


def _his_prompts(db) -> list[str]:
    return db.requests.distinct_positive_prompts()


class RequestAnswerer(QObject):
    def __init__(self, db, jobs, client, *, parent=None, **stand_ins):
        super().__init__(parent)
        self._db = db
        self._hold = jobs.model_hold if jobs is not None else None
        self._client = client
        self._notes_path = stand_ins.get("notes_path", config.COLLECTION_NOTES_PATH)
        self._work_out = stand_ins.get("work_out", prompt_edit.work_out)
        self._wait_for_the_graphics_card = stand_ins.get(
            "wait_for_the_graphics_card", graphics_card.wait_for_the_graphics_card)

    def ask(self, about: str | None, pair: tuple[str, str], words: str, *, owner: QObject, then,
            **told) -> None:
        exchange = _exchange_of(self._db, about)
        if self._hold is not None:
            self._hold.hold()
        run_off_thread(lambda: self._answer(pair, words, exchange, told),
                       lambda revision: self._deliver(owner, then, revision),
                       owner=self, waits_long=True)

    def _answer(self, pair: tuple[str, str], words: str, exchange, told: dict):
        try:
            if (self._client is not None
                    and not self._wait_for_the_graphics_card(self._client, HOLDER,
                                                    deadline_s=GRAPHICS_CARD_DEADLINE_S)):
                return prompt_edit.request_applier(told.get("in_scenes", False))(*pair, words)
            examples = prompt_edit.prompts_touching(
                words, reversed(_his_prompts(self._db)))
            return self._work_out(*pair, words, exchange=exchange,
                                  notes=collection_notes.read(self._notes_path),
                                  examples=examples, **told)
        except Exception as exc:  # noqa: BLE001 -- answered with nothing, never raised off-thread
            logger.warning("Could not work out a request (%s)", type(exc).__name__)
            return None
        finally:
            graphics_card.let_go_of_the_graphics_card()

    def _deliver(self, owner: QObject, then, revision) -> None:
        if self._hold is not None:
            self._hold.let_go()
        if sip.isdeleted(owner):
            logger.info("A request's answer came back after what asked for it was gone")
            return
        then(revision)
