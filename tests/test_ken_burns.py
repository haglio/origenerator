"""The slow push into a still — the arithmetic, with no window and no clock."""

from pytest import approx

from origenerator.ken_burns import (
    TICK_MS, ZOOM_SPAN, crop_box, progress_step, zoom_at,
)


def _run(dwell_ms: int, over_ms: int) -> float:
    """The zoom after *over_ms* of a slide whose dwell is *dwell_ms*."""
    progress = 0.0
    for _ in range(over_ms // TICK_MS):
        progress += progress_step(TICK_MS, dwell_ms)
    return zoom_at(progress)


def test_a_slide_ends_its_dwell_the_whole_span_deeper_in():
    assert _run(4000, 4000) == approx(ZOOM_SPAN)


def test_a_longer_dwell_covers_the_same_ground_more_slowly():
    # The point of the whole thing: three times the dwell is a third of the
    # speed, not three times the distance — travelling further would end on a
    # crop of the picture rather than on the picture.
    assert _run(12000, 4000) == approx(1 + (ZOOM_SPAN - 1) / 3)
    assert _run(12000, 12000) == approx(ZOOM_SPAN)


def test_a_pace_of_nought_never_moves():
    # Nought means the slide holds until an arrow moves it, and a picture being
    # held is not a shot being made.
    assert progress_step(TICK_MS, 0) == 0.0
    assert _run(0, 10_000) == 1.0


def test_the_move_stops_at_the_end_of_the_move():
    # A slide that outlives its dwell — locked part-way through, or ticked late
    # — stops there rather than carrying on into the picture forever.
    assert zoom_at(5.0) == approx(ZOOM_SPAN)
    assert zoom_at(-1.0) == 1.0


def test_the_crop_is_centered_and_a_share_of_each_side():
    assert crop_box(1000, 500, 1.25) == (100, 50, 800, 400)


def test_the_whole_picture_is_the_crop_at_the_start():
    assert crop_box(640, 480, 1.0) == (0, 0, 640, 480)


def test_the_crop_never_shrinks_away_to_nothing():
    # A silly zoom is still a rectangle something can be drawn from.
    x, y, width, height = crop_box(8, 8, 1000.0)
    assert (width, height) == (1, 1)
    assert (x, y) == (3, 3)
