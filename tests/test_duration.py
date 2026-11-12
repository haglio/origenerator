from __future__ import annotations

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef, chained_frames
from origenerator.workflows.duration import frames_for_seconds, lasting, on_grid, seconds_for_frames
from origenerator.workflows.frame_rate import NATIVE_FPS, playback_rate


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
    assert seconds_for_frames(161, 24.0, _frames()) == 6.7


def test_a_frame_rate_between_two_native_multiples_lands_where_the_graph_puts_it():
    rate_grid = ParamDef("frame_rate", "Frame Rate", "int", 16, min_val=NATIVE_FPS, max_val=64, step=NATIVE_FPS)

    for rate in (20, 24, 28, 40):
        assert on_grid(rate, rate_grid) == playback_rate(rate)


def test_a_frame_count_counts_from_one_not_from_the_fewest_the_model_renders():
    assert on_grid(6, _frames()) == 5
    assert on_grid(7, _frames()) == 9


def test_a_run_made_to_last_some_seconds_stretches_its_last_scene_to_reach_them():
    workflow = WORKFLOW_REGISTRY["wan22_i2v"]
    two_scenes = {**workflow.default_params(), "scene_frames": [81, 81]}

    lengthened = lasting(two_scenes, workflow, 15)

    assert lengthened["frame_count"] == 15 * NATIVE_FPS + 1
    assert chained_frames(lengthened["scene_frames"]) == lengthened["frame_count"]
    assert lengthened["scene_frames"][0] == 81


def test_a_run_whose_workflow_has_no_scenes_is_given_none():
    workflow = WORKFLOW_REGISTRY["wan22_i2v"]
    one_length = {key: value for key, value in workflow.default_params().items()
                  if key != "scene_frames"}

    assert "scene_frames" not in lasting(one_length, workflow, 15)
