from __future__ import annotations

import pytest

from origenerator.running_ahead import AheadWhilePlaying
from tests.running_ahead_support import recorded_block


def _recorded():
    block, raised = recorded_block()
    return AheadWhilePlaying(block), raised


def test_two_parts_playing_at_once_put_the_app_ahead_once():
    app, raised = _recorded()

    with app.held(), app.held():
        assert raised == ["ahead"]

    assert raised == ["ahead", "back"]


def test_the_app_stays_ahead_until_the_last_part_stops_whichever_stopped_first():
    app, raised = _recorded()
    slideshow, osr2 = app.held(), app.held()
    slideshow.__enter__()
    osr2.__enter__()

    slideshow.__exit__(None, None, None)
    assert raised == ["ahead"]

    osr2.__exit__(None, None, None)
    assert raised == ["ahead", "back"]


def test_a_part_that_fails_while_playing_still_lets_the_app_go_back():
    app, raised = _recorded()

    with pytest.raises(RuntimeError), app.held():
        raise RuntimeError("a made-up failure")

    assert raised == ["ahead", "back"]


def test_the_next_part_to_play_puts_the_app_ahead_again():
    app, raised = _recorded()
    with app.held():
        pass

    with app.held():
        pass

    assert raised == ["ahead", "back", "ahead", "back"]
