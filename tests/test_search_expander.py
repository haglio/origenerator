from __future__ import annotations

import threading

from PyQt6 import sip
from PyQt6.QtCore import QThreadPool

from origenerator.gui.search_expander import SearchExpander


def _settled(expander, qtbot):
    qtbot.waitUntil(lambda: not expander._in_flight, timeout=2000)


def test_a_widening_runs_on_the_pool_the_app_drains(qtbot):
    ran = threading.Event()

    def expand(query):
        ran.set()
        return {"tall": ("high",)}

    expander = SearchExpander(expand=expand)
    expander.request("tall")

    assert QThreadPool.globalInstance().waitForDone(3000)
    assert ran.is_set()
    _settled(expander, qtbot)


def test_a_request_widens_the_query_and_announces_it(qtbot):
    expander = SearchExpander(expand=lambda q: {"women": ("dolls",)})
    with qtbot.waitSignal(expander.expanded, timeout=2000) as blocker:
        assert expander.request("two women") is None

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
    calls = []
    expander = SearchExpander(expand=lambda q: calls.append(q) or {"a": ("b",)})
    with qtbot.waitSignal(expander.expanded, timeout=2000):
        expander.request("two women  ")
    expander.request("two of the women")
    _settled(expander, qtbot)

    assert len(calls) == 1


def test_cached_asks_nothing_and_starts_nothing(qtbot):
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
        assert expander.request("two women") is None
        release.set()

    assert calls == ["two women"]


def test_a_failing_widening_is_silence_rather_than_a_crash(qtbot):
    def explode(_query):
        raise RuntimeError("endpoint down")

    expander = SearchExpander(expand=explode)
    with qtbot.waitSignal(expander.expanded, timeout=2000) as blocker:
        expander.request("two women")

    assert blocker.args == ["two women", {}]


def test_a_wordless_query_is_never_sent(qtbot):
    calls = []
    expander = SearchExpander(expand=lambda q: calls.append(q) or {})

    assert expander.request("   ") is None

    assert calls == []


def test_a_widening_that_lands_after_its_expander_is_gone_is_dropped(qtbot):
    release = threading.Event()
    expander = SearchExpander(expand=lambda q: release.wait(3) and {"cat": ("kitten",)})
    expander.request("cat")
    sip.delete(expander)

    release.set()
    assert QThreadPool.globalInstance().waitForDone(3000)
    qtbot.wait(50)
