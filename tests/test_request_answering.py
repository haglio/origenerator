"""The one place a Request is asked of the model: off the UI thread, with the
item's exchange and the notes, the Job Queue's line held meanwhile."""
from __future__ import annotations

import logging
import threading

from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from origenerator import collection_notes
from origenerator.collection_notes import CollectionNotes
from origenerator.db import Database
from origenerator.gui.request_answering import RequestAnswerer


class _Jobs:
    def __init__(self):
        self.holds = 0
        self.let_go = 0

    def hold_for_the_model(self):
        self.holds += 1

    def the_model_let_go(self):
        self.let_go += 1


def _answerer(qtbot, tmp_path, *, work_out, wait=lambda comfyui, holder, **settings: True,
              client=object()):
    db = Database(tmp_path / "t.db")
    jobs = _Jobs()
    parent = QWidget()
    qtbot.addWidget(parent)
    answerer = RequestAnswerer(db, jobs, client, notes_path=tmp_path / "notes.json",
                               work_out=work_out, wait_for_the_card=wait, parent=parent)
    return answerer, db, jobs, parent


def test_the_model_is_asked_off_the_ui_thread_with_the_items_exchange_and_the_notes(
        qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, *, exchange, notes, examples, settings):
        seen.update(thread=threading.current_thread(), exchange=exchange, notes=notes,
                    asked=(positive, negative, words))
        return "the revision"

    answerer, db, jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    db.record_request(prompt_id="g1", source_prompt_id="src", heard="", asked="a hat")
    db.record_turns("g1", [("a hat", "Gave her a hat.")])
    collection_notes.write(tmp_path / "notes.json", CollectionNotes(
        prompt_count=3, batches=1, batch_notes=["a note"], patterns="the patterns"))
    answers = []

    answerer.ask("g1", "a woman, a hat", "blurry", "no hat", owner=parent, then=answers.append)

    assert jobs.holds == 1  # the line is held from the moment of asking
    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen["asked"] == ("a woman, a hat", "blurry", "no hat")
    assert [(turn.said, turn.answered) for turn in seen["exchange"]] == [("a hat", "Gave her a hat.")]
    assert seen["notes"].patterns == "the patterns"
    assert seen["thread"] is not threading.main_thread()
    assert jobs.let_go == 1


def test_an_item_nothing_was_asked_of_starts_with_no_exchange(qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, *, exchange, notes, examples, settings):
        seen.update(exchange=exchange, notes=notes, examples=examples)
        return "the revision"

    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    answers = []

    answerer.ask("fresh", "a woman", "", "a hat", owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen == {"exchange": [], "notes": None, "examples": []}


def test_his_own_prompts_that_touch_the_request_are_gathered_newest_first_for_the_model(
        qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, *, exchange, notes, examples, settings):
        seen["examples"] = examples
        return "the revision"

    answerer, db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    for pid, prompt in (("g1", "a dog on a park bench, wagging tail"),
                        ("g2", "a cat on a windowsill"),
                        ("g3", "two dogs chasing a stick, wagging tails")):
        db.insert_generation(prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
                             positive_prompt=prompt, params_json="{}", workflow_json="{}",
                             source="generated")
    answers = []

    answerer.ask("fresh", "a woman", "", "add a dog", owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen["examples"] == ["two dogs chasing a stick, wagging tails",
                                "a dog on a park bench, wagging tail"]


def test_the_line_is_let_go_even_when_the_one_who_asked_is_gone(qtbot, tmp_path):
    answerer, _db, jobs, _parent = _answerer(
        qtbot, tmp_path, work_out=lambda *args, **settings: "the revision")
    owner = QWidget()
    answers = []
    answerer.ask("g1", "a woman", "", "a hat", owner=owner, then=answers.append)
    owner.deleteLater()
    sip.delete(owner)

    qtbot.waitUntil(lambda: jobs.let_go == 1, timeout=5000)

    assert answers == []


def test_a_comfyui_that_stays_busy_leaves_the_rules_to_answer_without_the_model(qtbot, tmp_path):
    def never(*args, **settings):
        raise AssertionError("the model was asked")

    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=never,
                                             wait=lambda comfyui, holder, **settings: False)
    answers = []

    answerer.ask("g1", "a woman, a hat, soft light", "blurry", "no hat", owner=parent,
                 then=answers.append)

    qtbot.waitUntil(lambda: bool(answers), timeout=5000)
    assert answers[0].positive == "a woman, soft light"
    assert answers[0].answer == ""


def test_with_no_comfyui_the_card_is_not_waited_for(qtbot, tmp_path):
    def never_wait(comfyui, holder, **settings):
        raise AssertionError("waited")

    answerer, _db, _jobs, parent = _answerer(
        qtbot, tmp_path, work_out=lambda *args, **settings: "the revision", wait=never_wait,
        client=None)
    answers = []

    answerer.ask("g1", "a woman", "", "a hat", owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)


def test_a_failure_answers_with_nothing_and_logs_only_its_kind(qtbot, tmp_path, caplog):
    def boom(positive, negative, words, **settings):
        raise ValueError(f"cannot read {positive!r} or {negative!r} for {words!r}")

    answerer, _db, jobs, parent = _answerer(qtbot, tmp_path, work_out=boom)
    answers = []

    with caplog.at_level(logging.INFO, logger="origenerator.gui.request_answering"):
        answerer.ask("g1", "gamma form, an example lantern", "example flaws", "no example lantern",
                     owner=parent, then=answers.append)
        qtbot.waitUntil(lambda: answers == [None], timeout=5000)

    assert caplog.messages == ["Could not work out a request (ValueError)"]
    assert jobs.let_go == 1


def test_the_settings_he_may_change_ride_along_to_the_model(qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, **given):
        seen.update(given)
        return "the revision"

    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    answers = []

    answerer.ask(None, "a woman", "", "fewer steps", settings=("told",), owner=parent,
                 then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen["settings"] == ("told",)
