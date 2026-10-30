"""The notes the local model writes on the whole prompt collection; every prompt invented."""
from __future__ import annotations

import json
import logging

from origenerator import collection_notes
from origenerator.collection_notes import CollectionNotes

PROMPTS = [f"a baker {verb} in a quiet square, soft light, scene alpha"
           for verb in ("waving", "yawning", "reading", "sweeping", "humming")]


class _Model:
    def __init__(self, tokens_read=1000):
        self.asked = []
        self.tokens_read = tokens_read
        self.let_go_of = 0

    def let_go(self) -> None:
        self.let_go_of += 1

    def __call__(self, messages, **settings):
        self.asked.append((messages[-1]["content"], settings))
        content = ("PATTERNS: one line of comma-separated parts" if "PATTERNS" in messages[-1]["content"]
                   else f"Notes on batch {len(self.asked)}")
        return {"message": {"content": content}, "prompt_eval_count": self.tokens_read}


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 10.0
        return self.now


def test_prompts_are_dealt_into_batches_by_size_in_the_order_given():
    batches = list(collection_notes.batches(["aaaa", "bbbb", "cc", "dddddd"], limit=8))

    assert batches == [["aaaa", "bbbb"], ["cc", "dddddd"]]


def test_notes_are_due_when_there_are_none_and_once_the_collection_has_grown_a_tenth():
    assert collection_notes.due(None, prompt_count=12) is True
    written = CollectionNotes(prompt_count=100, batches=2, batch_notes=["a", "b"],
                              patterns="PATTERNS")

    assert collection_notes.due(written, prompt_count=109) is False
    assert collection_notes.due(written, prompt_count=110) is True


def test_notes_are_never_due_for_an_empty_collection():
    assert collection_notes.due(None, prompt_count=0) is False


def test_unfinished_notes_are_due_until_their_patterns_are_written():
    unfinished = CollectionNotes(prompt_count=100, batches=2, batch_notes=["a"], patterns="")

    assert collection_notes.due(unfinished, prompt_count=100) is True


def test_taking_notes_asks_one_note_per_batch_then_the_patterns_and_lets_the_model_go():
    model = _Model()

    notes = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=3600)

    assert notes.complete
    assert notes.batch_notes == ["Notes on batch 1", "Notes on batch 2", "Notes on batch 3"]
    assert notes.patterns == "PATTERNS: one line of comma-separated parts"
    assert notes.prompt_count == len(PROMPTS)
    assert [settings["stays_loaded"] for _text, settings in model.asked] == [None, None, None, "0"]
    assert {settings["reads_tokens"] for _text, settings in model.asked} == {
        collection_notes.WINDOW_TOKENS}
    assert PROMPTS[0] in model.asked[0][0] and PROMPTS[-1] in model.asked[2][0]
    assert "Notes on batch 1" in model.asked[3][0]  # the patterns are drawn from the notes


def test_a_time_budget_stops_the_taking_between_batches_and_a_later_taking_picks_up_there():
    model = _Model()
    first = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=15)
    assert first.complete is False
    assert first.batch_notes == ["Notes on batch 1"]
    assert model.let_go_of == 1  # the card is ComfyUI's again between sittings

    later = collection_notes.take(PROMPTS, first, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=3600)

    assert later.complete
    assert later.batch_notes == ["Notes on batch 1", "Notes on batch 2", "Notes on batch 3"]
    assert PROMPTS[0] not in model.asked[1][0]  # the first batch was not read again


def test_a_collection_that_changed_size_has_its_notes_started_over():
    model = _Model()
    first = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=15)

    later = collection_notes.take(PROMPTS[:-1], first, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=3600)

    assert later.prompt_count == len(PROMPTS) - 1
    assert PROMPTS[0] in model.asked[1][0]  # read again, from the start


def test_a_batch_that_fills_the_models_window_makes_the_batches_smaller_and_starts_over():
    model = _Model(tokens_read=collection_notes.WINDOW_TOKENS)

    notes = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=240, clock=_Clock(),
                                  budget_s=15)

    assert notes.complete is False
    assert notes.batch_notes == []
    assert notes.batch_chars == 120


def test_notes_come_back_from_their_file_and_a_missing_or_broken_file_is_none(tmp_path):
    path = tmp_path / "collection_notes.json"
    assert collection_notes.read(path) is None
    notes = CollectionNotes(prompt_count=5, batches=3, batch_notes=["a", "b"], patterns="", batch_chars=120)

    collection_notes.write(path, notes)
    assert collection_notes.read(path) == notes

    path.write_text("{not json", encoding="utf-8")
    assert collection_notes.read(path) is None


def test_taking_notes_logs_counts_and_times_never_a_prompt_or_a_note(caplog):
    model = _Model()
    with caplog.at_level(logging.INFO, logger="origenerator.collection_notes"):
        collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                              budget_s=3600)

    assert caplog.messages
    assert all("baker" not in line and "Notes on batch" not in line for line in caplog.messages)


def test_the_notes_file_is_written_whole_or_not_at_all(tmp_path):
    path = tmp_path / "notes" / "collection_notes.json"
    notes = CollectionNotes(prompt_count=1, batches=1, batch_notes=["a"], patterns="p")

    collection_notes.write(path, notes)

    assert json.loads(path.read_text(encoding="utf-8"))["patterns"] == "p"
    assert list(path.parent.iterdir()) == [path]  # no partial file left beside it
