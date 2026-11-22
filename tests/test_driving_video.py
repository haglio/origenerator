from __future__ import annotations

from origenerator.workflows.driving_video import frames_within, start_frame


def test_the_run_starts_the_whole_number_of_frames_into_the_video_nearest_the_seconds_asked():
    assert start_frame(0.0) == 0
    assert start_frame(2.03) == 32
    assert start_frame(2.04) == 33
    assert start_frame(-1.0) == 0


def test_a_run_takes_only_as_much_of_the_video_as_lies_past_its_start_on_the_models_grid():
    assert frames_within(81, video_seconds=4.0, start=16) == 45
    assert frames_within(81, video_seconds=10.0, start=16) == 81
    assert frames_within(81, video_seconds=None, start=16) == 81
    assert frames_within(81, video_seconds=1.0, start=16) == 5


