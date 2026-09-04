"""The slow push into a still — the arithmetic, with no window and no clock."""

from pytest import approx

from origenerator.ken_burns import (
    TICK_MS,
    ZOOM_SPAN,
    crop_box,
    progress_step,
    zoom_at,
)

# A whole tick of the standard dwell — what any of these can be out by, since a
# tick count is a whole number and a stretch of milliseconds need not divide by
# one. Far below anything an eye reads off the screen.
_ONE_TICK = (ZOOM_SPAN - 1) * TICK_MS / 4000


def _run(dwell_ms: int, over_ms: int) -> float:
    """The zoom after *over_ms* of a slide whose dwell is *dwell_ms*."""
    progress = 0.0
    for _ in range(round(over_ms / TICK_MS)):
        progress += progress_step(TICK_MS, dwell_ms)
    return zoom_at(progress)


def test_a_slide_ends_its_dwell_the_whole_span_deeper_in():
    assert _run(4000, 4000) == approx(ZOOM_SPAN, abs=_ONE_TICK)


def test_a_longer_dwell_covers_the_same_ground_more_slowly():
    # The point of the whole thing: three times the dwell is a third of the
    # speed, not three times the distance — travelling further would end on a
    # crop of the picture rather than on the picture.
    assert _run(12000, 4000) == approx(1 + (ZOOM_SPAN - 1) / 3, abs=_ONE_TICK)
    assert _run(12000, 12000) == approx(ZOOM_SPAN, abs=_ONE_TICK)


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
    assert crop_box(1000, 500, 1.25) == approx((100.0, 50.0, 800.0, 400.0))


def test_the_whole_picture_is_the_crop_at_the_start():
    assert crop_box(640, 480, 1.0) == approx((0.0, 0.0, 640.0, 480.0))


def test_the_crop_creeps_by_a_fraction_of_a_pixel_rather_than_holding_still():
    # The failure this replaced: a whole-pixel window over a move this slow
    # holds for several ticks and then steps, and the two axes step at
    # different moments -- which reads as the picture twitching, not creeping.
    # So consecutive ticks must differ, however slightly.
    steps = [crop_box(1920, 1080, zoom_at(tick * progress_step(TICK_MS, 4000)))
             for tick in range(4)]
    lefts = [box[0] for box in steps]
    assert len(set(lefts)) == len(lefts)
    assert 0 < lefts[1] - lefts[0] < 1  # under a pixel, and never nought
