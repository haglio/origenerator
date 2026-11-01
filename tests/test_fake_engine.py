from __future__ import annotations

from pathlib import Path

from tests.funestra_fakes import FakeEngine

ONE, TWO, THREE = Path("one.mp4"), Path("two.mp4"), Path("three.mp4")


def test_a_new_engine_holds_nothing_and_opens_heard_at_full_volume():
    engine = FakeEngine()

    assert (engine.opened, engine.opened_at_pace, engine.playlist) == ([], [], [])
    assert (engine.duration_ms, engine.position_ms, engine.frame_rate) == (5_000.0, 0.0, 25.0)
    assert (engine.volume, engine.muted, engine.speed) == (100, False, 1.0)
    assert (engine.paused, engine.loop_file, engine.closed, engine.idle) == (False,) * 4
    assert (engine.showing_image, engine.showing_video) == (False, True)


def test_its_length_is_a_keyword():
    assert FakeEngine(duration_ms=1_000.0).duration_ms == 1_000.0


def test_a_load_goes_back_to_the_start_and_notes_the_pace():
    engine = FakeEngine()
    engine.set_pace(3.0)
    engine.seek_ms(1_000.0)

    engine.load(ONE)

    assert (engine.opened, engine.opened_at_pace) == ([ONE], [3.0])
    assert (engine.playlist, engine.position_ms) == ([ONE], 0.0)


def test_a_stop_lets_go_and_leaves_the_position():
    engine = FakeEngine()
    engine.load(ONE)
    engine.seek_ms(1_000.0)

    engine.stop()

    assert (engine.stopped, engine.idle, engine.position_ms) == (True, True, 1_000.0)


def test_a_load_after_a_stop_is_no_longer_idle():
    engine = FakeEngine()
    engine.stop()

    engine.load(ONE)

    assert (engine.stopped, engine.idle) == (False, False)


def test_staging_replaces_what_was_staged():
    engine = FakeEngine()
    engine.load(ONE)
    engine.stage_next(TWO)

    engine.stage_next(THREE)

    assert (engine.playlist, engine.staged_next) == ([ONE, THREE], THREE)


def test_clearing_drops_what_was_staged():
    engine = FakeEngine()
    engine.load(ONE)
    engine.stage_next(TWO)

    engine.clear_next()

    assert (engine.playlist, engine.staged_next) == ([ONE], None)


def test_running_out_rolls_onto_what_was_staged():
    engine = FakeEngine()
    engine.load(ONE)
    engine.stage_next(TWO)
    assert engine.advanced_to_next is False

    engine.run_out()

    assert (engine.advanced_to_next, engine.on_screen, engine.staged_next) == (True, TWO, None)


def test_running_out_with_nothing_staged_stays_put():
    engine = FakeEngine()
    engine.load(ONE)

    engine.run_out()

    assert (engine.advanced_to_next, engine.on_screen) == (False, ONE)


def test_nothing_is_on_screen_before_anything_is_open():
    assert FakeEngine().on_screen is None


def test_settling_forgets_the_item_it_rolled_off_and_keeps_what_was_staged_after():
    engine = FakeEngine()
    engine.load(ONE)
    engine.stage_next(TWO)
    engine.run_out()
    engine.stage_next(THREE)

    engine.settle_on_the_next()

    assert (engine.playlist, engine.playlist_pos) == ([TWO, THREE], 0)


def test_staging_after_a_roll_keeps_the_item_it_rolled_off():
    engine = FakeEngine()
    engine.load(ONE)
    engine.stage_next(TWO)
    engine.run_out()

    engine.stage_next(THREE)

    assert (engine.playlist, engine.playlist_pos) == ([ONE, TWO, THREE], 1)


def test_staging_before_anything_is_open_is_the_first_entry():
    engine = FakeEngine()

    engine.stage_next(ONE)

    assert engine.playlist == [ONE]


def test_a_swap_replaces_the_item_on_screen():
    engine = FakeEngine()
    engine.load(ONE)

    engine.swap_still(TWO)

    assert (engine.swapped, engine.playlist) == ([TWO], [TWO])


def test_a_seek_is_recorded_as_asked_and_lands_within_the_length():
    engine = FakeEngine(duration_ms=1_000.0)

    engine.seek_ms(-5.0)
    assert engine.position_ms == 0.0
    engine.seek_ms(9_000.0)

    assert (engine.seeks, engine.position_ms) == ([-5.0, 9_000.0], 1_000.0)


def test_each_setting_is_held_as_given():
    engine = FakeEngine()

    engine.set_paused(True)
    engine.set_loop_file(True)
    engine.set_pace(3.0)
    engine.set_volume(40)
    engine.set_muted(True)
    engine.set_speed(2.0)
    engine.set_ab_loop(1.0, 2.0)
    engine.set_points_of_interest((1, 2))

    assert (engine.paused, engine.loop_file, engine.pace_s) == (True, True, 3.0)
    assert (engine.volume, engine.muted, engine.speed, engine.ab_loop) == (40, True, 2.0, (1.0, 2.0))
    assert engine.points_told == [(1, 2)]
    engine.clear_ab_loop()
    assert engine.ab_loop is None


def test_a_hold_of_nothing_is_no_hold():
    engine = FakeEngine()
    engine.hold_image_for(3.0)
    assert engine.held_for == 3.0

    engine.hold_image_for(0)

    assert engine.held_for is None


def test_a_still_counts_what_it_is_asked():
    engine = FakeEngine()

    engine.push_still()
    engine.seek_image(500.0)

    assert (engine.pushes, engine.image_seeks) == (1, [500.0])


def test_a_screenshot_answers_what_it_was_given():
    engine = FakeEngine()
    assert engine.screenshot_bgra() is None
    engine.screenshot = b"frame"

    assert engine.screenshot_bgra() == b"frame"


def test_overlays_are_held_by_their_id_and_removing_a_missing_one_is_nothing():
    engine = FakeEngine()

    engine.overlay(1, 2, 3, b"drawn")
    assert engine.overlays == {1: (2, 3, b"drawn")}
    engine.remove_overlay(1)
    engine.remove_overlay(1)

    assert engine.overlays == {}


def test_closing_is_remembered():
    engine = FakeEngine()

    engine.close()

    assert engine.closed is True


def test_tiling_to_fill_is_asked_of_it_and_changes_nothing_it_holds():
    engine = FakeEngine()
    before = dict(vars(engine))

    engine.tile_to_fill(640, 480)

    assert vars(engine) == before
