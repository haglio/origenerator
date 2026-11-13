from __future__ import annotations

from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    frames_filled_in,
    playback_rate,
    rate_multiplier,
    rate_options,
)


def test_the_native_rate_needs_no_frames_between_its_frames():
    assert rate_multiplier(NATIVE_FPS) == 1
    assert playback_rate(NATIVE_FPS) == 16.0


def test_a_whole_multiple_of_the_native_rate_is_one_multiplier():
    assert [rate_multiplier(r) for r in (32, 48, 64, 80, 96, 112)] == [2, 3, 4, 5, 6, 7]
    assert [playback_rate(r) for r in (32, 48, 112)] == [32.0, 48.0, 112.0]


def test_a_rate_between_two_multiples_is_written_at_the_nearer_one():
    assert (rate_multiplier(60), playback_rate(60)) == (4, 64.0)
    assert (rate_multiplier(24), playback_rate(24)) == (2, 32.0)
    assert (rate_multiplier(30), playback_rate(30)) == (2, 32.0)


def test_a_rate_past_the_fastest_is_written_at_the_fastest():
    assert MAX_PLAYBACK_FPS == 7 * NATIVE_FPS
    for asked in (113, 120, 128, 240, 10_000):
        assert playback_rate(asked) == MAX_PLAYBACK_FPS


def test_a_rate_under_the_native_one_still_plays_at_true_speed():
    assert (rate_multiplier(8), playback_rate(8)) == (1, 16.0)
    assert (rate_multiplier(0), playback_rate(0)) == (1, 16.0)



def test_a_model_made_at_another_rate_fills_in_whole_multiples_of_its_own_rate():
    assert [playback_rate(r, 24.0) for r in (24, 48, 60, 72, 96)] == [24.0, 48.0, 48.0, 72.0, 96.0]
    assert rate_multiplier(1000, 24.0) == 4
    assert rate_options(24.0) == [24, 48, 72, 96]
    assert rate_options(NATIVE_FPS) == [16, 32, 48, 64, 80, 96, 112]


def test_the_frames_in_the_file_count_from_the_models_own_rate():
    assert frames_filled_in(73, 48.0, 24.0) == 145
