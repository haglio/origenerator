from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QWidget

from origenerator.gui.deferred import defer


def _pump(qtbot, ms=100):
    qtbot.wait(ms)


def test_deferred_work_runs_on_the_next_turn(qtbot):
    owner = QWidget()
    qtbot.addWidget(owner)
    ran = []

    defer(owner, lambda: ran.append("now"))

    assert ran == []
    _pump(qtbot)
    assert ran == ["now"]


def test_work_deferred_by_a_dead_owner_never_runs(qtbot):
    owner = QWidget()
    ran = []
    defer(owner, lambda: ran.append("stale"))

    owner.deleteLater()
    del owner
    _pump(qtbot)

    assert ran == []


def test_the_deferred_call_is_owned_by_the_asker(qtbot):
    owner = QObject()
    defer(owner, lambda: None)

    (timer,) = [c for c in owner.children() if isinstance(c, QTimer)]
    assert timer.isSingleShot()
    assert timer.isActive()


def test_the_work_is_dropped_once_it_has_run(qtbot):
    owner = QObject()
    ran = []
    defer(owner, lambda: ran.append(1))

    (timer,) = [c for c in owner.children() if isinstance(c, QTimer)]
    _pump(qtbot)

    assert ran == [1]
    assert timer._work is None


def test_each_deferral_is_its_own_pending_call(qtbot):
    owner = QObject()
    ran = []

    defer(owner, lambda: ran.append("first"))
    defer(owner, lambda: ran.append("second"))
    _pump(qtbot)

    assert ran == ["first", "second"]
