from origenerator.workflows.base import ParamDef
from origenerator.workflows.duration import frames_for_seconds, seconds_for_frames


def _frames(max_val=161):
    return ParamDef("frame_count", "Duration", "int", 81,
                    min_val=5, max_val=max_val, step=4)


def test_seconds_become_the_nearest_frame_count_on_the_models_grid():
    assert frames_for_seconds(5, 16.0, _frames()) == 81
    assert frames_for_seconds(5, 24.0, _frames()) == 121
    assert frames_for_seconds(1, 16.0, _frames()) == 17
    assert frames_for_seconds(5, 30.0, _frames()) == 149


def test_a_length_past_what_the_model_renders_stops_at_its_last_grid_step():
    assert frames_for_seconds(30, 16.0, _frames()) == 161
    assert frames_for_seconds(30, 16.0, _frames(max_val=113)) == 113
    assert frames_for_seconds(30, 16.0, _frames(max_val=160)) == 157
    assert frames_for_seconds(0, 16.0, _frames()) == 5


def test_a_frame_count_reads_back_as_the_shortest_seconds_that_reproduce_it():
    assert seconds_for_frames(81, 16.0, _frames()) == 5
    assert seconds_for_frames(121, 24.0, _frames()) == 5
    assert seconds_for_frames(21, 16.0, _frames()) == 1.3
    assert seconds_for_frames(113, 16.0, _frames(max_val=113)) == 7


def test_a_clip_cut_short_by_the_model_reads_back_at_its_real_length():
    # 161 frames at 24 fps is 6.7 s; "7" would only round-trip through the clamp.
    assert seconds_for_frames(161, 24.0, _frames()) == 6.7
