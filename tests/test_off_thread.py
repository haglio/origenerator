"""Handing one slow call to the pool — and what has to survive until it answers."""
from __future__ import annotations

import gc
import threading

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject

from origenerator.gui.off_thread import _in_flight, _Result, _Task, run_off_thread


@pytest.fixture
def owner():
    return QObject()


def _wait_for(qtbot, got, ms=5000):
    qtbot.waitUntil(lambda: bool(got), timeout=ms)


def test_the_answer_comes_back_on_the_calling_thread(qtbot, owner):
    got = []
    here = threading.get_ident()

    run_off_thread(lambda: 21 * 2, lambda value: got.append((value, threading.get_ident())),
                   owner=owner)
    _wait_for(qtbot, got)

    assert got == [(42, here)]   # the value, on the thread that asked for it


def test_a_raised_call_answers_none_rather_than_losing_the_caller(qtbot, owner):
    # A failure is a result like any other; the caller's own fallback decides
    # what no answer means, and an exception on a pool thread is simply lost.
    got = []

    def boom():
        raise RuntimeError("nope")

    run_off_thread(boom, got.append, owner=owner)
    _wait_for(qtbot, got)

    assert got == [None]


def test_a_collection_mid_flight_does_not_take_the_answer_with_it(qtbot, owner):
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

    run_off_thread(slow, got.append, owner=owner)
    assert started.wait(5)
    for _ in range(3):
        gc.collect()          # exactly what used to take it
    release.set()
    _wait_for(qtbot, got)

    assert got == ["answered"]


def test_the_carrier_is_held_from_a_root_until_it_delivers(qtbot, owner):
    # Not a cycle: something outside points at it for as long as it may still be
    # called, and nothing does once it has.
    got = []
    before = len(_in_flight)

    run_off_thread(lambda: 1, got.append, owner=owner)
    assert len(_in_flight) == before + 1

    _wait_for(qtbot, got)
    assert len(_in_flight) == before


def test_an_answer_whose_carrier_the_app_took_on_its_way_out_is_let_go_of(qtbot):
    result = _Result()
    sip.delete(result)  # what the interpreter's exit does to every carrier still waiting

    _Task(lambda: "too late", result).run()


def test_an_answer_that_lands_after_its_owner_is_gone_is_dropped(qtbot, owner):
    release, got = threading.Event(), []
    before = set(_in_flight)

    run_off_thread(lambda: release.wait(5) and "late", got.append, owner=owner)
    carrier = _in_flight - before
    sip.delete(owner)
    release.set()
    qtbot.waitUntil(lambda: not carrier & _in_flight, timeout=5000)

    assert got == []


def test_each_call_carries_its_own_answer(qtbot, owner):
    got = []

    run_off_thread(lambda: "a", got.append, owner=owner)
    run_off_thread(lambda: "b", got.append, owner=owner)
    qtbot.waitUntil(lambda: len(got) == 2, timeout=5000)

    assert sorted(got) == ["a", "b"]


def test_a_call_that_may_wait_minutes_holds_neither_the_pool_nor_the_apps_exit(qtbot, owner):
    got = []

    def where():
        thread = threading.current_thread()
        return type(thread) is threading.Thread, thread.daemon

    run_off_thread(where, got.append, owner=owner, waits_long=True)
    _wait_for(qtbot, got)

    assert got == [(True, True)]
