from __future__ import annotations

from origenerator.gui.holdable_timer import HoldableTimer


def test_a_timer_held_part_way_through_stops_and_keeps_what_was_left(qtbot):
    timer = HoldableTimer()
    timer.run_for(60_000)

    timer.hold(True)

    assert not timer.isActive()
    timer.hold(False)
    assert timer.isActive()
    assert 0 < timer.interval() <= 60_000


def test_letting_go_of_a_timer_nothing_held_starts_nothing(qtbot):
    timer = HoldableTimer()

    timer.hold(False)

    assert not timer.isActive()


def test_a_cancelled_timer_forgets_the_time_it_was_held_with(qtbot):
    timer = HoldableTimer()
    timer.run_for(60_000)
    timer.hold(True)

    timer.cancel()
    timer.hold(False)

    assert not timer.isActive()


def test_a_timer_run_again_while_held_starts_over_rather_than_resuming(qtbot):
    timer = HoldableTimer()
    timer.run_for(60_000)
    timer.hold(True)

    timer.run_for(5_000)
    timer.hold(False)

    assert timer.isActive()
    assert timer.interval() == 5_000


def test_it_fires_once(qtbot):
    timer = HoldableTimer()

    assert timer.isSingleShot()
