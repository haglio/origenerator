from __future__ import annotations

import json
from dataclasses import asdict

from origenerator.collection_notes import CollectionNotes
from origenerator.request_measure import Case, cases_in, main, measured

_BEACH = "a man on a beach, white sand, blue sea"
_WITH_A_HAT = "a man on a beach, a wide straw hat, frayed brim, white sand, blue sea"
_FOREST = "a man in a forest, tall pines, morning fog"
_PROMPTS = [
    (_FOREST, "blurry"),
    (f"{_FOREST}, a wide straw hat, frayed brim", "blurry, bare head"),
    (_BEACH, "blurry"),
    (_WITH_A_HAT, "blurry, bare head"),
    (f"{_BEACH}, zeppelin", "blurry"),
]
_THE_HAT = Case((_BEACH, "blurry"), (_WITH_A_HAT, "blurry, bare head"), "hat", 3)
_THE_BRIM = Case((_BEACH, "blurry"), (_WITH_A_HAT, "blurry, bare head"), "brim", 3)


def test_a_case_is_an_edit_of_his_asked_for_by_the_last_word_he_had_written_before():
    assert cases_in(_PROMPTS) == [_THE_HAT, _THE_BRIM]


def _scores(answered: tuple[str, str]) -> list[str]:
    seen = []

    def answer(pair, request, his_prompts):
        seen.append((pair, request, his_prompts))
        return answered

    lines = measured([_THE_HAT], _PROMPTS, answer, clock=iter([10.0, 12.5]).__next__).lines()
    assert seen == [((_BEACH, "blurry"), "add hat", _PROMPTS[:3])]
    return lines


def test_an_answer_that_is_his_own_edit_scores_full_marks():
    assert _scores((_WITH_A_HAT, "blurry, bare head")) == [
        "Requests measured: 1",
        "The thing went in in the words you wrote it in: 100%",
        "Nothing off topic went in: 100%",
        "Off-topic parts per Request: 0.00",
        "Of the parts you added, went in: 100%",
        "Of the parts that went in, you had added: 100%",
        "Exactly your edit: 100%",
        "Seconds per Request: 2.5",
    ]


def test_an_answer_that_changes_nothing_scores_nothing_and_adds_nothing_off_topic():
    assert _scores((_BEACH, "blurry"))[1:7] == [
        "The thing went in in the words you wrote it in: 0%",
        "Nothing off topic went in: 100%",
        "Off-topic parts per Request: 0.00",
        "Of the parts you added, went in: 0%",
        "Of the parts that went in, you had added: -",
        "Exactly your edit: 0%",
    ]


def test_parts_that_share_no_word_with_his_edit_are_counted_off_topic_in_either_prompt():
    assert _scores((f"{_BEACH}, a felt hat, two sailors", "blurry, bare head, rain"))[1:7] == [
        "The thing went in in the words you wrote it in: 0%",
        "Nothing off topic went in: 0%",
        "Off-topic parts per Request: 2.00",
        "Of the parts you added, went in: 33%",
        "Of the parts that went in, you had added: 25%",
        "Exactly your edit: 0%",
    ]


def _notes(tmp_path):
    path = tmp_path / "collection_notes.json"
    path.write_text(json.dumps(asdict(CollectionNotes(
        prompt_count=3, batches=1, patterns="Hats come with frayed brims."))), encoding="utf-8")
    return path


def test_the_measurement_answers_as_the_app_does_and_writes_only_its_scores(tmp_path):
    shown, left = [], []
    scores = tmp_path / "state" / "scores.txt"

    main(["5"], scores_path=scores, shown=shown.append, his_prompts=lambda: _PROMPTS,
         take=lambda: True, leave=lambda: left.append("left"),
         ask=lambda messages, **how: {"message": {"content": '{"changes": []}'}})

    assert shown == [scores]
    assert scores.read_text(encoding="utf-8").splitlines()[:3] == [
        "Requests measured: 2",
        "The thing went in in the words you wrote it in: 100%",
        "Nothing off topic went in: 100%",
    ]
    assert left == []


def test_a_measurement_that_asks_the_model_takes_the_graphics_card_once_and_gives_it_back(tmp_path):
    taken, left, told = [], [], []
    prompts = [("a dog showing teeth", ""), (_BEACH, ""), (f"{_BEACH}, a cat showing claws", "")]

    main(["5"], scores_path=tmp_path / "scores.txt", shown=lambda path: None,
         his_prompts=lambda: prompts, take=lambda: taken.append("taken") or True,
         leave=lambda: left.append("left"), notes_path=_notes(tmp_path),
         ask=lambda messages, **how: told.extend(messages) or {"message": {"content": '{"changes": []}'}})

    assert (taken, left) == (["taken"], ["left"])
    assert "Hats come with frayed brims." in told[-1]["content"]
