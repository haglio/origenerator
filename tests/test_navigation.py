from __future__ import annotations

from origenerator.navigation import NavigationHistory


def test_new_history_cannot_move_in_either_direction():
    history = NavigationHistory()
    assert history.current() is None
    assert not history.can_go_back()
    assert not history.can_go_forward()


def test_visiting_builds_a_stack_that_back_and_forward_traverse():
    history = NavigationHistory()
    history.visit("a")
    history.visit("b")
    history.visit("c")
    assert history.current() == "c"
    assert history.can_go_back()
    assert not history.can_go_forward()

    assert history.back() == "b"
    assert history.back() == "a"
    assert not history.can_go_back()
    assert history.forward() == "b"
    assert history.can_go_back()
    assert history.can_go_forward()


def test_back_and_forward_return_none_at_the_ends():
    history = NavigationHistory()
    history.visit("only")
    assert history.back() is None
    assert history.forward() is None
    assert history.current() == "only"


def test_revisiting_the_current_location_is_a_noop():
    history = NavigationHistory()
    history.visit("a")
    history.visit("a")
    history.visit("a")
    assert history.current() == "a"
    assert not history.can_go_back(), (
        "revisiting the current location is a no-op, so the gallery's refresh-driven "
        "reselection of the same view never piles up duplicates")


def test_visiting_after_going_back_drops_the_forward_branch():
    history = NavigationHistory()
    history.visit("a")
    history.visit("b")
    history.visit("c")
    history.back()
    history.visit("d")
    assert history.current() == "d"
    assert not history.can_go_forward()
    assert history.back() == "b"
    assert history.back() == "a"


def test_replacing_overwrites_where_the_cursor_stands_without_stacking_a_stop():
    history = NavigationHistory()
    history.visit("a")
    history.visit("b")

    history.replace("b typed")

    assert history.current() == "b typed"
    assert history.back() == "a"
    assert history.forward() == "b typed"
    assert not history.can_go_forward()


def test_replacing_drops_the_forward_tail():
    history = NavigationHistory()
    for name in ("a", "b", "c"):
        history.visit(name)
    history.back()

    history.replace("b again")

    assert history.current() == "b again"
    assert not history.can_go_forward(), (
        "what the forward stops branched from is no longer what is on screen")


def test_replacing_in_an_empty_history_visits():
    history = NavigationHistory()

    history.replace("a")

    assert history.current() == "a"
    assert not history.can_go_back()
