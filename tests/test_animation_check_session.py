"""Walking the table's animations one at a time, accepting the settings each runs.

Acts and states are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest

from origenerator.animation_check_session import AnimationCheckSession
from origenerator.recipe_match import GENAU, VIDEO

_ORDER = [
    (VIDEO, "alpha", "state one"),
    (VIDEO, "beta", "state two"),
    (GENAU, "alpha", "state two"),
]


class _Store:
    def __init__(self):
        self.accepted = {}

    def remember(self, lane, act, state, *, workflow, params):
        self.accepted[(lane, act, state)] = (workflow, dict(params))

    def accepted_paths(self):
        return set(self.accepted)

    def assigned(self, lane, act, state):
        held = self.accepted.get((lane, act, state))
        return None if held is None else {"workflow": held[0], "params": held[1]}


def _clip(prompt_id, *, positive="a scene", negative="flaws", steps=8):
    return {
        "prompt_id": prompt_id, "workflow_name": "wan22_i2v",
        "positive_prompt": positive, "negative_prompt": negative,
        "params_json": json.dumps({"positive_prompt": positive,
                                   "negative_prompt": negative, "steps": steps,
                                   "input_image": "pic.png [output]"}),
    }


@pytest.fixture
def session():
    def build(samples=None, store=None, order=None, pinned=None):
        return AnimationCheckSession(order or _ORDER, samples or {},
                                     store or _Store(), pinned=pinned)

    return build


def test_it_opens_on_the_first_animation_with_its_example(session):
    clip = _clip("one")
    made = session({(VIDEO, "alpha", "state one"): [clip]})

    assert made.path == (VIDEO, "alpha", "state one")
    assert made.sample is clip
    assert made.position == (1, 3)


def test_an_animation_with_no_example_comes_up_blank_rather_than_skipped(session):
    made = session({})

    assert made.path == (VIDEO, "alpha", "state one")
    assert made.sample is None


def test_accepting_records_the_samples_settings_and_moves_on(session):
    store = _Store()
    made = session({(VIDEO, "alpha", "state one"): [_clip("one")]}, store)

    made.accept(positive="a better scene", negative="flaws")

    assert store.accepted[(VIDEO, "alpha", "state one")] == (
        "wan22_i2v", {"positive_prompt": "a better scene", "negative_prompt": "flaws",
                      "steps": 8, "input_image": "pic.png [output]"})
    assert made.path == (VIDEO, "beta", "state two")


def test_rejecting_an_example_brings_up_the_next_one_for_the_same_animation(session):
    first, second = _clip("one"), _clip("two")
    made = session({(VIDEO, "alpha", "state one"): [first, second]})

    made.next_sample()

    assert made.path == (VIDEO, "alpha", "state one")
    assert made.sample is second


def test_rejecting_the_last_example_leaves_the_animation_blank(session):
    made = session({(VIDEO, "alpha", "state one"): [_clip("one")]})

    made.next_sample()

    assert made.path == (VIDEO, "alpha", "state one")
    assert made.sample is None


def test_going_forward_leaves_the_animation_as_it_was_and_shows_the_next(session):
    store = _Store()
    made = session({(VIDEO, "alpha", "state one"): [_clip("one")]}, store)

    made.forward()

    assert [made.position, made.path] == [(2, 3), (VIDEO, "beta", "state two")]
    assert store.accepted == {}


def test_going_forward_from_the_last_stays_there(session):
    made = session({})
    for _ in _ORDER:
        made.forward()

    made.forward()

    assert made.position == (len(_ORDER), len(_ORDER))


def test_going_back_shows_the_one_before(session):
    made = session({})
    made.forward()

    made.back()

    assert made.path == (VIDEO, "alpha", "state one")
    assert made.position == (1, 3)


def test_going_back_from_the_first_stays_there(session):
    made = session({})

    made.back()

    assert made.position == (1, 3)


def test_the_last_animation_answered_leaves_nothing_on_screen(session):
    made = session({})
    for _ in _ORDER:
        made.accept(positive="a scene", negative="flaws")

    assert made.path is None
    assert made.sample is None


def test_it_says_how_many_of_the_table_already_have_settings(session):
    store = _Store()
    store.remember(*_ORDER[1], workflow="wan22_i2v", params={})
    made = session({}, store)

    assert made.answered == 1


_PINNED = {"workflow": "wan22_i2v", "params": {"positive_prompt": "the act's own",
                                               "negative_prompt": "", "steps": 6}}


def test_an_animation_nobody_kept_a_video_of_starts_from_the_acts_own_settings(session):
    made = session({}, pinned=lambda act, lane: _PINNED)

    assert made.sample is None
    assert made.starting_point["params"]["positive_prompt"] == "the act's own"


def test_assigning_from_the_acts_own_settings_keeps_their_workflow(session):
    store = _Store()
    made = session({}, store, pinned=lambda act, lane: _PINNED)

    made.accept(positive="mine", negative="none")

    workflow, params = store.accepted[(VIDEO, "alpha", "state one")]
    assert workflow == "wan22_i2v"
    assert params == {"positive_prompt": "mine", "negative_prompt": "none", "steps": 6}


def test_an_animation_with_neither_a_sample_nor_an_act_recipe_starts_from_nothing(
        session):
    made = session({})

    assert made.starting_point is None


def test_assigning_saves_the_prompts_he_typed_with_nothing_else_to_go_on():
    """His words, on an animation with no kept video and no act settings behind
    it: "assign should still save those prompts; that's not nothing"."""
    store = _Store()
    session = AnimationCheckSession(_ORDER, {}, store)

    session.accept(positive="a scene", negative="its flaws")

    assert store.accepted[_ORDER[0]] == (
        "", {"positive_prompt": "a scene", "negative_prompt": "its flaws"})


def test_an_animation_he_has_assigned_opens_on_what_he_assigned():
    """What he assigned is the answer for that animation, so it is what comes up
    when the walk reaches it again -- not the sample's own prompts."""
    store = _Store()
    store.accepted[_ORDER[0]] = ("wan22_i2v", {"positive_prompt": "what he typed"})
    session = AnimationCheckSession(_ORDER, {_ORDER[0]: [_clip("kept")]}, store)

    assert session.starting_point == {
        "workflow": "wan22_i2v", "params": {"positive_prompt": "what he typed"}}
