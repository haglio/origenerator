"""What one "animate as" comes to for the image actually on screen.

Acts and states are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from origenerator.action_settings import GENAU, VIDEO
from origenerator.animate_command import AnimateRequest, Answer, what_to_animate

_PATHS = {
    "animation_paths": {
        VIDEO: {"alpha": ["state one", "state two"], "beta": ["state two"]},
        GENAU: {"alpha": ["state two"]},
    },
}


def _asked(lane, act, state):
    return what_to_animate(AnimateRequest(lane, act), state, content=_PATHS)


def test_an_act_the_image_can_do_is_what_gets_animated():
    assert _asked(VIDEO, "alpha", "state one") == Answer("alpha")


def test_an_act_the_image_cannot_do_is_refused_as_something_it_cannot_do():
    answer = _asked(VIDEO, "beta", "state one")

    assert answer.act is None
    assert answer.unsupported
    assert "beta" in answer.said
    assert "state one" in answer.said


def test_an_unsaid_act_is_the_one_the_image_leaves_no_choice_about():
    assert _asked(GENAU, "", "state two") == Answer("alpha")
    assert _asked(VIDEO, "", "state one") == Answer("alpha")


def test_an_unsaid_act_with_a_choice_to_make_is_asked_about_not_refused():
    answer = _asked(VIDEO, "", "state two")

    assert answer.act is None
    assert not answer.unsupported
    assert "alpha" in answer.said
    assert "beta" in answer.said


def test_an_image_nothing_can_be_made_of_in_this_lane_is_refused_too():
    answer = _asked(GENAU, "", "state one")

    assert answer.act is None
    assert answer.unsupported
    assert "state one" in answer.said


def test_an_image_nobody_has_sorted_yet_is_asked_about_before_anything_is_run():
    answer = _asked(VIDEO, "alpha", "")

    assert answer.act is None
    assert not answer.unsupported
    assert "sorted" in answer.said
