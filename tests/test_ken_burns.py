from __future__ import annotations

from pytest import approx

from origenerator.ken_burns import ZOOM_SPAN, PushClock, zoom_at


def test_the_move_stops_at_the_end_of_the_move():
    assert zoom_at(5.0) == approx(ZOOM_SPAN)
    assert zoom_at(-1.0) == 1.0


def test_the_push_is_as_far_through_its_move_as_the_dwell_that_has_passed():
    clock = PushClock()
    clock.start(now_ms=1000, dwell_ms=4000)

    assert clock.progress(now_ms=2000) == approx(0.25)


def test_the_push_starts_over_once_a_whole_move_has_passed():
    clock = PushClock()
    clock.start(now_ms=0, dwell_ms=4000)

    assert clock.progress(now_ms=5000) == approx(0.25)


def test_time_spent_paused_does_not_move_the_push_on():
    clock = PushClock()
    clock.start(now_ms=0, dwell_ms=4000)
    clock.pause(now_ms=1000)
    clock.resume(now_ms=3000)

    assert clock.progress(now_ms=4000) == approx(0.5)


def test_a_new_pace_carries_the_push_on_from_where_it_had_got_to():
    clock = PushClock()
    clock.start(now_ms=0, dwell_ms=4000)
    clock.retime(now_ms=2000, dwell_ms=8000)

    assert clock.progress(now_ms=2000) == approx(0.5)
    assert clock.progress(now_ms=4000) == approx(0.75)


def test_a_push_can_start_part_way_through_its_move():
    clock = PushClock()
    clock.start(now_ms=1000, dwell_ms=4000, progress=0.25)

    assert clock.progress(now_ms=1000) == approx(0.25)
    assert clock.progress(now_ms=2000) == approx(0.5)
