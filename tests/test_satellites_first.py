from __future__ import annotations

from PySide6.QtCore import QObject

from origenerator.gui.satellites_first import SatellitesFirst

_NEVER_MS = 600_000


def _waiting(qtbot, served, *, wait_ms=_NEVER_MS):
    owner = QObject()
    first = SatellitesFirst(owner, served=served, wait_ms=wait_ms)
    first.owner = owner
    return first


def test_what_waits_runs_once_the_satellites_have_their_lists(qtbot):
    have = []
    ran = []
    first = _waiting(qtbot, lambda: bool(have))
    first.then(lambda: ran.append("drawn"))
    qtbot.wait(150)
    assert ran == []

    have.append("lists")

    qtbot.waitUntil(lambda: ran == ["drawn"])


def test_what_waits_runs_when_the_wait_is_over_though_a_satellite_never_took_a_list(qtbot):
    ran = []
    first = _waiting(qtbot, lambda: False, wait_ms=50)
    first.then(lambda: ran.append("drawn"))

    qtbot.waitUntil(lambda: ran == ["drawn"])


def test_what_waits_runs_in_the_order_it_was_asked_and_only_once(qtbot):
    ran = []
    first = _waiting(qtbot, lambda: True)
    first.then(lambda: ran.append("the window's own draw"))
    first.then(lambda: ran.append("the library's tidying"))

    qtbot.waitUntil(lambda: len(ran) == 2)
    qtbot.wait(250)

    assert ran == ["the window's own draw", "the library's tidying"]


def test_what_is_asked_after_the_satellites_were_served_runs_at_once(qtbot):
    first = _waiting(qtbot, lambda: True)
    qtbot.waitUntil(lambda: first.over)
    ran = []

    first.then(lambda: ran.append("late"))

    assert ran == ["late"]
