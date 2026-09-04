"""Handing one slow call to the pool — and what has to survive until it answers."""

import gc
import threading

from origenerator.gui.off_thread import _in_flight, run_off_thread


def _wait_for(qtbot, got, ms=5000):
    qtbot.waitUntil(lambda: bool(got), timeout=ms)


def test_the_answer_comes_back_on_the_calling_thread(qtbot):
    got = []
    here = threading.get_ident()

    run_off_thread(lambda: 21 * 2, lambda value: got.append((value, threading.get_ident())))
    _wait_for(qtbot, got)

    assert got == [(42, here)]   # the value, on the thread that asked for it


def test_a_raised_call_answers_none_rather_than_losing_the_caller(qtbot):
    # A failure is a result like any other; the caller's own fallback decides
    # what no answer means, and an exception on a pool thread is simply lost.
    got = []

    def boom():
        raise RuntimeError("nope")

    run_off_thread(boom, got.append)
    _wait_for(qtbot, got)

    assert got == [None]


def test_a_collection_mid_flight_does_not_take_the_answer_with_it(qtbot):
    """The crash this module cost, in the small.

    The carrier used to be kept alive by being a reference cycle and nothing
    else, so a collection between the pool thread's emit and the delivery freed
    the handler that the queued call was about to reach — an access violation
    with no traceback, not a lost callback.
    """
    started, release, got = threading.Event(), threading.Event(), []

    def slow():
        started.set()
        release.wait(5)
        return "answered"

    run_off_thread(slow, got.append)
    assert started.wait(5)
    for _ in range(3):
        gc.collect()          # exactly what used to take it
    release.set()
    _wait_for(qtbot, got)

    assert got == ["answered"]


def test_the_carrier_is_held_from_a_root_until_it_delivers(qtbot):
    # Not a cycle: something outside points at it for as long as it may still be
    # called, and nothing does once it has.
    got = []
    before = len(_in_flight)

    run_off_thread(lambda: 1, got.append)
    assert len(_in_flight) == before + 1

    _wait_for(qtbot, got)
    assert len(_in_flight) == before


def test_each_call_carries_its_own_answer(qtbot):
    got = []

    run_off_thread(lambda: "a", got.append)
    run_off_thread(lambda: "b", got.append)
    qtbot.waitUntil(lambda: len(got) == 2, timeout=5000)

    assert sorted(got) == ["a", "b"]
