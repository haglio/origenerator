from __future__ import annotations

from app_support.threading_utils import wait_until
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from origenerator.gui.satellites_first import LONGEST_WAIT_S, SatellitesFirst


class _Clock:
    def __init__(self) -> None:
        self.at = 0.0

    def __call__(self) -> float:
        return self.at


def _waiting(served, clock=None):
    owner = QObject()
    first = SatellitesFirst(owner, served=served, now=clock or _Clock())
    first.owner = owner
    return first


def _until(condition):
    wait_until(condition, pump=QApplication.processEvents)


def test_what_waits_runs_once_the_satellites_have_their_lists(qtbot):
    have = []
    ran = []
    first = _waiting(lambda: bool(have))
    first.then(lambda: ran.append("drawn"))
    first.look()
    assert ran == []

    have.append("lists")

    _until(lambda: ran == ["drawn"])


def test_what_waits_runs_when_the_wait_is_over_though_a_satellite_never_took_a_list(qtbot):
    ran = []
    clock = _Clock()
    first = _waiting(lambda: False, clock)
    first.then(lambda: ran.append("drawn"))
    first.look()
    assert ran == []

    clock.at = LONGEST_WAIT_S

    _until(lambda: ran == ["drawn"])


def test_what_waits_runs_in_the_order_it_was_asked_and_only_once(qtbot):
    ran = []
    first = _waiting(lambda: True)
    first.then(lambda: ran.append("the window's own draw"))
    first.then(lambda: ran.append("the library's tidying"))

    _until(lambda: len(ran) == 2)
    first.look()

    assert ran == ["the window's own draw", "the library's tidying"]


def test_what_is_asked_after_the_satellites_were_served_runs_at_once(qtbot):
    first = _waiting(lambda: True)
    _until(lambda: first.over)
    ran = []

    first.then(lambda: ran.append("late"))

    assert ran == ["late"]


def test_what_waits_runs_one_piece_a_turn_so_the_window_answers_between_them(qtbot):
    ran = []
    first = _waiting(lambda: True)
    first.then(lambda: ran.append("the panes"))
    first.then(lambda: ran.append("the library"))

    first.look()

    assert ran == ["the panes"]
    _until(lambda: ran == ["the panes", "the library"])


def test_what_is_asked_while_the_pieces_still_wait_their_turn_runs_after_them(qtbot):
    ran = []
    first = _waiting(lambda: True)
    first.then(lambda: ran.append("the panes"))
    first.then(lambda: ran.append("the library"))
    first.look()

    first.then(lambda: ran.append("late"))

    _until(lambda: len(ran) == 3)
    assert ran == ["the panes", "the library", "late"]


def test_a_piece_handed_off_the_windows_thread_holds_back_what_waits_until_it_is_done(qtbot):
    ran = []
    said_done = []
    first = _waiting(lambda: True)
    first.then_after(lambda done: (ran.append("the library, handed off"), said_done.append(done)))
    first.then(lambda: ran.append("the window is built"))
    first.look()
    QApplication.processEvents()

    first.then(lambda: ran.append("late"))
    QApplication.processEvents()
    assert ran == ["the library, handed off"]

    said_done[0]()
    _until(lambda: len(ran) == 3)
    assert ran == ["the library, handed off", "the window is built", "late"]
