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
    assert history.can_go_back() and not history.can_go_forward()

    assert history.back() == "b"
    assert history.back() == "a"
    assert not history.can_go_back()
    assert history.forward() == "b"
    assert history.can_go_back() and history.can_go_forward()


def test_back_and_forward_return_none_at_the_ends():
    history = NavigationHistory()
    history.visit("only")
    assert history.back() is None      # already at the oldest
    assert history.forward() is None   # already at the newest
    assert history.current() == "only"


def test_revisiting_the_current_location_is_a_noop():
    # Refresh re-selects the same generation constantly; that must not pile up.
    history = NavigationHistory()
    history.visit("a")
    history.visit("a")
    history.visit("a")
    assert history.current() == "a"
    assert not history.can_go_back()


def test_visiting_after_going_back_drops_the_forward_branch():
    history = NavigationHistory()
    history.visit("a")
    history.visit("b")
    history.visit("c")
    history.back()          # now at "b"
    history.visit("d")      # a new branch replaces "c"
    assert history.current() == "d"
    assert not history.can_go_forward()
    assert history.back() == "b"
    assert history.back() == "a"
