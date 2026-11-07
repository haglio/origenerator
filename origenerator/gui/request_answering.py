from __future__ import annotations

import logging

from PyQt6 import sip
from PyQt6.QtCore import QObject

from origenerator import collection_notes, config, graphics_card, local_llm, prompt_edit
from origenerator.gui.off_thread import run_off_thread

logger = logging.getLogger(__name__)

GRAPHICS_CARD_DEADLINE_S = 600.0
HOLDER = "Origenerator's Request"


def _exchange_of(db, about: str | None) -> list:
    return db.requests.exchange_of(about) if about else []


def _his_prompts(db) -> list[str]:
    return db.requests.distinct_positive_prompts()


def leave_the_graphics_card(*, unload=local_llm.let_go,
                            give_back=graphics_card.let_go_of_the_graphics_card) -> None:
    try:
        unload(base_url=config.LOCAL_LLM_BASE_URL, model=config.REQUEST_LLM_MODEL)
    except Exception as exc:  # noqa: BLE001 -- Ollama not answering has no model loaded to unload
        logger.info("The Request's model could not be told to leave (%s)", type(exc).__name__)
    finally:
        give_back()


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
        self._leave_the_graphics_card = stand_ins.get(
            "leave_the_graphics_card", leave_the_graphics_card)

    def ask(self, about: str | None, pair: tuple[str, str], words: str, *, owner: QObject, then,
            **told) -> None:
        exchange = [*_exchange_of(self._db, about), *told.pop("since", ())]
        still_loaded = self._hold is not None and self._hold.hold()
        run_off_thread(lambda: self._answer(pair, words, exchange, told, still_loaded),
                       lambda answered: self._deliver(owner, then, answered),
                       owner=self, waits_long=True)

    def _answer(self, pair: tuple[str, str], words: str, exchange, told: dict, still_loaded: bool):
        by_the_model = still_loaded
        try:
            by_the_model = still_loaded or self._takes_the_graphics_card()
            return self._worked_out(pair, words, exchange, told, by_the_model), by_the_model
        except Exception as exc:  # noqa: BLE001 -- answered with nothing, never raised off-thread
            logger.warning("Could not work out a request (%s)", type(exc).__name__)
            return None, by_the_model
        finally:
            if not by_the_model:
                graphics_card.let_go_of_the_graphics_card()
            elif self._hold is None:
                self._leave_the_graphics_card()

    def _takes_the_graphics_card(self) -> bool:
        return self._client is None or self._wait_for_the_graphics_card(
            self._client, HOLDER, deadline_s=GRAPHICS_CARD_DEADLINE_S)

    def _worked_out(self, pair: tuple[str, str], words: str, exchange, told: dict, by_the_model: bool):
        if not by_the_model:
            return prompt_edit.unanswered(*pair, words, prompt_edit.NO_GRAPHICS_CARD)
        examples = prompt_edit.prompts_touching(words, reversed(_his_prompts(self._db)))
        return self._work_out(*pair, words, exchange=exchange,
                              notes=collection_notes.read(self._notes_path),
                              examples=examples, **told)

    def _deliver(self, owner: QObject, then, answered) -> None:
        revision, model_stays = answered
        if self._hold is not None:
            self._hold.let_go(self._leave_the_graphics_card if model_stays else None)
        if sip.isdeleted(owner):
            logger.info("A request's answer came back after what asked for it was gone")
            return
        then(revision)
