from __future__ import annotations

import logging
import threading

from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from origenerator import collection_notes, config
from origenerator.collection_notes import CollectionNotes
from origenerator.db import Database, NewGeneration, NewRequest
from origenerator.db_requests import Turn
from origenerator.gui.request_answering import RequestAnswerer, leave_the_graphics_card
from origenerator.prompt_edit import NO_GRAPHICS_CARD
from origenerator.queue_line import ModelHold


class _Jobs:
    def __init__(self):
        self.let_go = 0
        self.model_hold = ModelHold(self._count)

    def _count(self):
        self.let_go += 1


_A_CLIENT = object()


def _answerer(qtbot, tmp_path, *, work_out, wait=lambda comfyui, holder, **settings: True,
              client=_A_CLIENT, **stand_ins):
    db = Database(tmp_path / "t.db")
    jobs = stand_ins.pop("jobs", _Jobs())
    parent = QWidget()
    qtbot.addWidget(parent)
    answerer = RequestAnswerer(db, jobs, client, notes_path=tmp_path / "notes.json",
                               work_out=work_out, wait_for_the_graphics_card=wait, parent=parent,
                               leave_the_graphics_card=stand_ins.pop("leave_the_graphics_card", lambda: None))
    return answerer, db, jobs, parent


def test_the_model_is_asked_off_the_ui_thread_with_the_items_exchange_and_the_notes(
        qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, **known):
        seen.update(thread=threading.current_thread(), exchange=known["exchange"], notes=known["notes"],
                    asked=(positive, negative, words))
        return "the revision"

    answerer, db, jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    db.record_request(NewRequest(prompt_id="g1", source_prompt_id="src", heard="", asked="a hat"))
    db.requests.record_turns("g1", [("a hat", "Gave her a hat.")])
    collection_notes.write(tmp_path / "notes.json", CollectionNotes(
        prompt_count=3, batches=1, batch_notes=["a note"], patterns="the patterns"))
    answers = []

    answerer.ask("g1", ("a woman, a hat", "blurry"), "no hat", owner=parent, then=answers.append)

    assert jobs.model_hold
    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen["asked"] == ("a woman, a hat", "blurry", "no hat")
    assert [(turn.said, turn.answered) for turn in seen["exchange"]] == [("a hat", "Gave her a hat.")]
    assert seen["notes"].patterns == "the patterns"
    assert seen["thread"] is not threading.main_thread()
    assert jobs.let_go == 1


def test_what_was_asked_since_the_item_was_shown_follows_its_saved_exchange(qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, **known):
        seen.update(exchange=known["exchange"])
        return "the revision"

    answerer, db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    db.record_request(NewRequest(prompt_id="g1", source_prompt_id="src", heard="", asked="a hat"))
    db.requests.record_turns("g1", [("a hat", "Gave her a hat.")])
    answers = []

    answerer.ask("g1", ("a woman, a hat, a scarf", "blurry"), "no scarf",
                 since=[Turn("a scarf", "Gave her a scarf.")], owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert [(turn.said, turn.answered) for turn in seen["exchange"]] == [
        ("a hat", "Gave her a hat."), ("a scarf", "Gave her a scarf.")]


def test_an_item_nothing_was_asked_of_starts_with_no_exchange(qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, **known):
        seen.update(exchange=known["exchange"], notes=known["notes"], examples=known["examples"])
        return "the revision"

    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    answers = []

    answerer.ask("fresh", ("a woman", ""), "a hat", owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen == {"exchange": [], "notes": None, "examples": []}


def test_his_own_prompts_that_touch_the_request_are_gathered_newest_first_for_the_model(
        qtbot, tmp_path):
    seen = {}

    def work_out(positive, negative, words, **known):
        seen["examples"] = known["examples"]
        return "the revision"

    answerer, db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    for pid, prompt in (("g1", "a dog on a park bench, wagging tail"),
                        ("g2", "a cat on a windowsill"),
                        ("g3", "two dogs chasing a stick, wagging tails")):
        db.insert_generation(NewGeneration(prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
                             positive_prompt=prompt, params_json="{}", workflow_json="{}",
                             source="generated"))
    answers = []

    answerer.ask("fresh", ("a woman", ""), "add a dog", owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen["examples"] == ["two dogs chasing a stick, wagging tails",
                                "a dog on a park bench, wagging tail"]


def test_the_line_is_let_go_even_when_the_one_who_asked_is_gone(qtbot, tmp_path):
    answerer, _db, jobs, _parent = _answerer(
        qtbot, tmp_path, work_out=lambda *args, **settings: "the revision")
    owner = QWidget()
    answers = []
    answerer.ask("g1", ("a woman", ""), "a hat", owner=owner, then=answers.append)
    owner.deleteLater()
    sip.delete(owner)

    qtbot.waitUntil(lambda: jobs.let_go == 1, timeout=5000)

    assert answers == []


def test_a_comfyui_that_stays_busy_answers_that_the_model_could_not_get_the_graphics_card(
        qtbot, tmp_path):
    def never(*args, **settings):
        raise AssertionError("the model was asked")

    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=never,
                                             wait=lambda comfyui, holder, **settings: False)
    answers = []

    answerer.ask("g1", ("a woman, a hat, soft light", "blurry"), "no hat", owner=parent,
                 then=answers.append)

    qtbot.waitUntil(lambda: bool(answers), timeout=5000)
    assert (answers[0].positive, answers[0].negative) == ("a woman, a hat, soft light", "blurry")
    assert answers[0].answer == NO_GRAPHICS_CARD


def test_with_no_comfyui_the_card_is_not_waited_for(qtbot, tmp_path):
    def never_wait(comfyui, holder, **settings):
        raise AssertionError("waited")

    answerer, _db, _jobs, parent = _answerer(
        qtbot, tmp_path, work_out=lambda *args, **settings: "the revision", wait=never_wait,
        client=None)
    answers = []

    answerer.ask("g1", ("a woman", ""), "a hat", owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)


def test_a_failure_answers_with_nothing_and_logs_only_its_kind(qtbot, tmp_path, caplog):
    def boom(positive, negative, words, **settings):
        raise ValueError(f"cannot read {positive!r} or {negative!r} for {words!r}")

    answerer, _db, jobs, parent = _answerer(qtbot, tmp_path, work_out=boom)
    answers = []

    with caplog.at_level(logging.INFO, logger="origenerator.gui.request_answering"):
        answerer.ask("g1", ("gamma form, an example lantern", "example flaws"), "no example lantern",
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

    answerer.ask(None, ("a woman", ""), "fewer steps", settings=("told",), owner=parent,
                 then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert seen["settings"] == ("told",)


def test_a_request_about_a_story_is_worked_out_scene_by_scene(qtbot, tmp_path):
    told = {}

    def work_out(positive, negative, words, **given):
        told.update(given)
        return "the revision"

    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=work_out)
    answers = []

    answerer.ask(None, ("a dog", ""), "a hat", in_scenes=True, owner=parent, then=answers.append)

    qtbot.waitUntil(lambda: answers == ["the revision"], timeout=5000)
    assert told["in_scenes"] is True


def _answered(qtbot, answerer, parent, words="a hat"):
    answers = []
    answerer.ask("g1", ("a woman", ""), words, owner=parent, then=answers.append)
    qtbot.waitUntil(lambda: len(answers) == 1, timeout=5000)
    return answers[0]


def _the_revision(*_args, **_known):
    return "the revision"


def test_the_model_stays_on_the_graphics_card_after_an_answer_until_it_is_sent_away(qtbot, tmp_path):
    left = []
    answerer, _db, jobs, parent = _answerer(qtbot, tmp_path, work_out=_the_revision,
                                            leave_the_graphics_card=lambda: left.append("left"))

    _answered(qtbot, answerer, parent)

    assert jobs.model_hold.stays
    assert left == []
    jobs.model_hold.send_away()()
    assert left == ["left"]


def test_a_request_asked_while_the_model_is_still_loaded_does_not_wait_for_the_card_again(
        qtbot, tmp_path):
    waited = []

    def wait(comfyui, holder, **settings):
        waited.append(holder)
        return True

    answerer, _db, jobs, parent = _answerer(qtbot, tmp_path, work_out=_the_revision, wait=wait)
    _answered(qtbot, answerer, parent)

    assert _answered(qtbot, answerer, parent, "a scarf") == "the revision"

    assert len(waited) == 1
    assert jobs.model_hold.stays


def test_an_answer_given_without_the_card_leaves_no_model_to_send_away(qtbot, tmp_path):
    answerer, _db, jobs, parent = _answerer(qtbot, tmp_path, work_out=None,
                                            wait=lambda comfyui, holder, **settings: False)

    _answered(qtbot, answerer, parent)

    assert not jobs.model_hold.stays


def test_with_no_job_queue_to_send_it_away_the_model_leaves_as_soon_as_it_has_answered(
        qtbot, tmp_path):
    left = []
    answerer, _db, _jobs, parent = _answerer(qtbot, tmp_path, work_out=_the_revision, jobs=None,
                                             leave_the_graphics_card=lambda: left.append("left"))

    _answered(qtbot, answerer, parent)

    assert left == ["left"]


def test_leaving_the_card_unloads_the_requests_model_and_gives_the_claim_back():
    done = []

    leave_the_graphics_card(unload=lambda **model: done.append(model), give_back=lambda: done.append("claim"))

    assert done == [{"base_url": config.LOCAL_LLM_BASE_URL, "model": config.REQUEST_LLM_MODEL},
                    "claim"]


def test_the_claim_is_given_back_though_the_model_could_not_be_told_to_leave():
    done = []

    def unload(**_model):
        raise OSError("Ollama is not running")

    leave_the_graphics_card(unload=unload, give_back=lambda: done.append("claim"))

    assert done == ["claim"]
