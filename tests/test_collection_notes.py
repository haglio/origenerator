from __future__ import annotations

import json
import logging

from origenerator import collection_notes, config
from origenerator.collection_notes import CollectionNotes
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database, NewGeneration
from tests.comfyui_folders import SUITE_FOLDERS

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
    assert PROMPTS[0] in model.asked[0][0]
    assert PROMPTS[-1] in model.asked[2][0]
    assert "Notes on batch 1" in model.asked[3][0]


def test_a_time_budget_stops_the_taking_between_batches_and_a_later_taking_picks_up_there():
    model = _Model()
    first = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=15)
    assert first.complete is False
    assert first.batch_notes == ["Notes on batch 1"]
    assert model.let_go_of == 1

    later = collection_notes.take(PROMPTS, first, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=3600)

    assert later.complete
    assert later.batch_notes == ["Notes on batch 1", "Notes on batch 2", "Notes on batch 3"]
    assert PROMPTS[0] not in model.asked[1][0]


def test_a_collection_that_changed_size_has_its_notes_started_over():
    model = _Model()
    first = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=15)

    later = collection_notes.take(PROMPTS[:-1], first, ask=model, let_go=model.let_go, batch_chars=120, clock=_Clock(),
                                  budget_s=3600)

    assert later.prompt_count == len(PROMPTS) - 1
    assert PROMPTS[0] in model.asked[1][0]


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
    assert list(path.parent.iterdir()) == [path]


def test_the_notes_as_the_model_is_told_them_lead_with_the_patterns_then_each_batch():
    notes = CollectionNotes(prompt_count=5, batches=2, batch_notes=["first", "second"],
                            patterns="the patterns")

    told = notes.as_told()

    assert told.index("the patterns") < told.index("first") < told.index("second")


def test_a_long_set_of_notes_is_cut_to_what_fits_from_the_end():
    notes = CollectionNotes(prompt_count=5, batches=3, batch_notes=["x" * 50, "y" * 50, "z" * 50],
                            patterns="p" * 20)

    told = notes.as_told(limit_chars=100)

    assert "p" * 20 in told
    assert "x" * 50 in told
    assert "z" * 50 not in told


def test_taking_the_notes_waits_for_the_card_reads_the_collection_and_writes_the_file(
        tmp_path):
    db = Database(tmp_path / "t.db")
    for pid, prompt in (("g1", "a baker waving, soft light"), ("g2", "a baker yawning, soft light")):
        db.insert_generation(NewGeneration(prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
                             positive_prompt=prompt, params_json="{}", workflow_json="{}"))
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    waited = []

    def wait(comfyui, holder, **settings):
        waited.append(comfyui)
        return True

    asked = []

    def ask(messages, **settings):
        asked.append((messages[-1]["content"], settings))
        return {"message": {"content": "PATTERNS" if "PATTERNS" in messages[-1]["content"]
                            else "a note"}, "prompt_eval_count": 50}

    path = tmp_path / "collection_notes.json"
    collection_notes.take_a_sitting(db, client, path, wait=wait, ask=ask, let_go=lambda **settings: None)

    assert waited == [client]
    assert {settings["model"] for _text, settings in asked} == {config.LOCAL_LLM_MODEL}
    notes = collection_notes.read(path)
    assert notes.complete
    assert notes.prompt_count == 2
    assert collection_notes.are_due(db, path) is False


def test_notes_the_model_could_not_be_asked_for_are_left_for_the_next_turn(
        tmp_path, caplog):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(prompt_id="g1", workflow_name="sdxl_t2i", workflow_version="v002",
                         positive_prompt="a baker waving", params_json="{}", workflow_json="{}"))
    def down(messages, **settings):
        raise OSError("Ollama is not running")

    with caplog.at_level(logging.INFO, logger="origenerator.collection_notes"):
        collection_notes.take_a_sitting(db, ComfyUIClient(folders=SUITE_FOLDERS),
                                        tmp_path / "collection_notes.json",
                                        wait=lambda comfyui, holder, **settings: True, ask=down)

    assert not (tmp_path / "collection_notes.json").exists()
    assert any("Ollama is not running" in line for line in caplog.messages)
    assert all("baker" not in line for line in caplog.messages)


def test_a_sitting_with_the_graphics_card_taken_asks_nothing_and_writes_nothing(tmp_path):
    def never(*args, **settings):
        raise AssertionError("the model is not asked")

    collection_notes.take_a_sitting(Database(tmp_path / "t.db"), None, tmp_path / "notes.json",
                                    wait=lambda comfyui, holder, **settings: False, ask=never)

    assert not (tmp_path / "notes.json").exists()


def test_a_sitting_out_of_time_before_the_patterns_lets_the_model_go_and_keeps_the_notes():
    model = _Model()

    notes = collection_notes.take(PROMPTS, None, ask=model, let_go=model.let_go, clock=_Clock(),
                                  batch_chars=10_000, budget_s=25.0)

    assert notes.batch_notes
    assert not notes.complete
    assert model.let_go_of == 1
