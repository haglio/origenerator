"""The background widener behind the gallery search box.

Everything here is about not making the user wait and not asking the model
twice: the deterministic results are already on screen by the time this is
called, so a slow, failing, or repeated request must cost nothing visible.
"""

import threading

from origenerator.gui.search_expander import SearchExpander


def _settled(expander, qtbot):
    """Wait for every worker the expander has started to have finished."""
    qtbot.waitUntil(lambda: not expander._in_flight, timeout=2000)


def test_a_request_widens_the_query_and_announces_it(qtbot):
    expander = SearchExpander(expand=lambda q: {"women": ("dolls",)})
    with qtbot.waitSignal(expander.expanded, timeout=2000) as blocker:
        assert expander.request("two women") is None  # nothing known yet

    assert blocker.args == ["two women", {"women": ("dolls",)}]


def test_an_answered_query_comes_back_without_asking_again(qtbot):
    calls = []

    def expand(query):
        calls.append(query)
        return {"women": ("dolls",)}

    expander = SearchExpander(expand=expand)
    with qtbot.waitSignal(expander.expanded, timeout=2000):
        expander.request("two women")

    assert expander.request("two women") == {"women": ("dolls",)}
    _settled(expander, qtbot)
    assert calls == ["two women"]


def test_the_same_question_worded_differently_is_one_request(qtbot):
    # Trailing spaces and stop words are not a new question for the model.
    calls = []
    expander = SearchExpander(expand=lambda q: calls.append(q) or {"a": ("b",)})
    with qtbot.waitSignal(expander.expanded, timeout=2000):
        expander.request("two women  ")
    expander.request("two of the women")
    _settled(expander, qtbot)

    assert len(calls) == 1


def test_cached_asks_nothing_and_starts_nothing(qtbot):
    # What a keystroke consults: typing must cost lookups, not a call per
    # character.
    calls = []
    expander = SearchExpander(expand=lambda q: calls.append(q) or {})

    assert expander.cached("two women") is None

    assert calls == []
    assert not expander._in_flight


def test_a_query_already_in_flight_starts_no_second_worker(qtbot):
    release = threading.Event()
    calls = []

    def expand(query):
        calls.append(query)
        release.wait(2)
        return {"women": ("dolls",)}

    expander = SearchExpander(expand=expand)
    with qtbot.waitSignal(expander.expanded, timeout=3000):
        expander.request("two women")
        qtbot.waitUntil(lambda: bool(calls), timeout=2000)
        assert expander.request("two women") is None  # the pending call answers it
        release.set()

    assert calls == ["two women"]


def test_a_failing_widening_is_silence_rather_than_a_crash(qtbot):
    def explode(_query):
        raise RuntimeError("endpoint down")

    expander = SearchExpander(expand=explode)
    with qtbot.waitSignal(expander.expanded, timeout=2000) as blocker:
        expander.request("two women")

    assert blocker.args == ["two women", {}]  # nothing added; the table tier stands


def test_a_wordless_query_is_never_sent(qtbot):
    calls = []
    expander = SearchExpander(expand=lambda q: calls.append(q) or {})

    assert expander.request("   ") is None

    assert calls == []
