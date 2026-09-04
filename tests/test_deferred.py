"""Deferring work to the next turn — and what happens when its owner goes first."""

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QWidget

from origenerator.gui.deferred import defer


def _pump(qtbot, ms=100):
    """Turn the event loop long enough for a zero-millisecond timer to fire."""
    qtbot.wait(ms)


def test_deferred_work_runs_on_the_next_turn(qtbot):
    owner = QWidget()
    qtbot.addWidget(owner)
    ran = []

    defer(owner, lambda: ran.append("now"))

    assert ran == []            # not this turn: that is the whole point
    _pump(qtbot)
    assert ran == ["now"]


def test_work_deferred_by_a_dead_owner_never_runs(qtbot):
    """The crash this exists to stop, in the small.

    A pane that redraws between the post and the delivery destroys the widget
    the work was for. Left to ``QTimer.singleShot``, the call still arrives --
    at a proxy PyQt owns, holding a callable nothing kept alive. Owned by the
    widget, the pending call goes when the widget does.
    """
    owner = QWidget()
    ran = []
    defer(owner, lambda: ran.append("stale"))

    owner.deleteLater()
    del owner
    _pump(qtbot)

    assert ran == []


def test_the_deferred_call_is_owned_by_the_asker(qtbot):
    # Not free-floating: it is a child, so the owner's destruction reaches it.
    owner = QObject()
    defer(owner, lambda: None)

    (timer,) = [c for c in owner.children() if isinstance(c, QTimer)]
    assert timer.isSingleShot()
    assert timer.isActive()


def test_the_work_is_dropped_once_it_has_run(qtbot):
    # Held only until it may still run — a captured widget is not kept alive by
    # a timer that has already fired.
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

    assert ran == ["first", "second"]   # in the order they were asked for
