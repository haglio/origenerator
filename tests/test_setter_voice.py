from __future__ import annotations

from origenerator.action_vocabulary import vocabulary
from origenerator.media import MediaType
from origenerator.setter_voice import PRESS, SAME, SKIP, TRASH, UNDO, Heard, setter_words

_CONTENT = {"image_actions": {
    "buttons": {"alpha": ["alpha"], "beta + gamma": ["beta", "gamma"]},
    "heard_as": {"alpha": ["al fa"]},
}}


def _words():
    return setter_words(vocabulary(MediaType.IMAGE, _CONTENT))


def test_a_buttons_name_said_presses_it():
    assert _words().heard("alpha") == Heard(PRESS, "alpha")


def test_a_button_is_heard_by_each_way_the_listener_writes_its_name():
    assert _words().heard("al fa") == Heard(PRESS, "alpha")


def test_a_button_joined_with_a_plus_is_said_with_plus():
    assert _words().heard("beta plus gamma") == Heard(PRESS, "beta + gamma")


def test_the_words_under_the_buttons_say_what_they_do():
    words = _words()

    assert [words.heard(said) for said in ("skip", "same", "same as last", "undo", "trash")] == [
        Heard(SKIP), Heard(SAME), Heard(SAME), Heard(UNDO), Heard(TRASH)]


def test_what_the_setter_tool_does_not_know_it_does_not_hear():
    assert _words().heard("go to recents") is None


def test_the_words_it_listens_for_are_every_one_it_knows():
    assert _words().phrases >= {"alpha", "al fa", "beta plus gamma", "skip", "same as last",
                                "trash"}
