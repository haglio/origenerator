from __future__ import annotations

from origenerator.workflows.driving_video import driven_actions, frames_within, start_frame


def test_the_run_starts_the_whole_number_of_frames_into_the_video_nearest_the_seconds_asked():
    assert start_frame(0.0) == 0
    assert start_frame(2.03) == 32        # 2.03 s at 16 fps is 32.48 frames
    assert start_frame(2.04) == 33
    assert start_frame(-1.0) == 0


def test_a_run_takes_only_as_much_of_the_video_as_lies_past_its_start_on_the_models_grid():
    assert frames_within(81, video_seconds=4.0, start=16) == 45   # 64 frames, 48 past the start, 45 on the grid
    assert frames_within(81, video_seconds=10.0, start=16) == 81
    assert frames_within(81, video_seconds=None, start=16) == 81
    assert frames_within(81, video_seconds=1.0, start=16) == 5


_SCRIPT = [{"at": 0, "pos": 0}, {"at": 500, "pos": 100}, {"at": 1500, "pos": 0},
           {"at": 2500, "pos": 100}, {"at": 3500, "pos": 0}]


def test_the_scripts_stretch_is_cut_out_and_moved_to_start_at_zero():
    assert driven_actions(_SCRIPT, start_ms=1000, length_ms=2000) == [
        {"at": 0, "pos": 50}, {"at": 500, "pos": 0}, {"at": 1500, "pos": 100}, {"at": 2000, "pos": 50},
    ]


def test_a_stretch_past_either_end_of_the_script_holds_the_devices_nearest_position():
    assert driven_actions(_SCRIPT, start_ms=3000, length_ms=2000) == [
        {"at": 0, "pos": 50}, {"at": 500, "pos": 0}, {"at": 2000, "pos": 0},
    ]
    assert driven_actions([{"at": 1000, "pos": 80}, {"at": 2000, "pos": 20}], start_ms=0, length_ms=500) == [
        {"at": 0, "pos": 80}, {"at": 500, "pos": 80},
    ]


def test_an_action_sitting_on_a_cut_is_kept_once():
    assert driven_actions(_SCRIPT, start_ms=500, length_ms=1000) == [
        {"at": 0, "pos": 100}, {"at": 1000, "pos": 0},
    ]


def test_a_video_with_no_script_drives_nothing():
    assert driven_actions([], start_ms=0, length_ms=1000) == []
