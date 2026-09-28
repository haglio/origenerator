from __future__ import annotations

from pathlib import Path

import pytest
from app_support.funscript import read_actions
from player_core.robot_hand import RobotHandState, bpm_for_speed

from origenerator.config import MOTION_DEFAULT_HZ
from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    heatmap_colors,
    resynthesize_funscript,
    synthesize_actions,
    synthesize_funscript,
    write_funscript,
)
from origenerator.workflows.frame_rate import NATIVE_FPS


def test_a_script_goes_in_the_scripts_folder_under_the_folders_its_video_is_in():
    assert funscript_path_for(
        Path("/out/video/wan22_i2v_00001_.mp4"), output_dir=Path("/out")
    ) == Path("/out/funscript/video/wan22_i2v_00001_.mp4.funscript")
    assert funscript_path_for("/out/deep/nested/clip.webm", output_dir="/out") == Path(
        "/out/funscript/deep/nested/clip.webm.funscript")


def test_a_video_outside_the_output_dir_has_its_script_in_the_scripts_folder_itself():
    assert funscript_path_for("deep/nested/clip.webm", output_dir="/out") == Path(
        "/out/funscript/clip.webm.funscript")


def test_two_videos_with_one_name_each_have_a_script_of_their_own(tmp_path):
    alpha = tmp_path / "alpha" / "clip.mp4"
    beta = tmp_path / "beta" / "deeper" / "clip.webm"
    write_funscript(tmp_path / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0))
    lengths = {alpha: 2.0, beta: 5.0}

    for video in lengths:
        synthesize_funscript(video, hz=1.0, output_dir=tmp_path,
                             duration_provider=lengths.get)

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, output_dir=tmp_path)) == synthesize_actions(
            seconds, hz=1.0)


def test_two_videos_of_one_name_in_one_folder_each_have_a_script_of_their_own(tmp_path):
    lengths = {tmp_path / "alpha" / "clip.mp4": 2.0, tmp_path / "alpha" / "clip.webm": 5.0}

    for video in lengths:
        synthesize_funscript(video, hz=1.0, output_dir=tmp_path,
                             duration_provider=lengths.get)

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, output_dir=tmp_path)) == synthesize_actions(
            seconds, hz=1.0)


def test_a_videos_own_script_is_found_before_those_older_versions_filed(tmp_path):
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    assert funscript_of(video, output_dir=tmp_path) is None

    beside = video.with_suffix(".funscript")
    beside.write_text("{}", encoding="utf-8")
    assert funscript_of(video, output_dir=tmp_path) == beside

    filed_under_its_stem = tmp_path / "funscript" / "clip.funscript"
    filed_under_its_stem.parent.mkdir()
    filed_under_its_stem.write_text("{}", encoding="utf-8")
    assert funscript_of(video, output_dir=tmp_path) == filed_under_its_stem

    own = funscript_path_for(video, output_dir=tmp_path)
    own.parent.mkdir()
    own.write_text("{}", encoding="utf-8")
    assert funscript_of(video, output_dir=tmp_path) == own


def test_a_script_written_before_the_folder_existed_is_still_found(tmp_path):
    """Hundreds sit beside their clips. A reader that knew only the new place
    would drop the motion from every one of them, silently."""
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    beside = video.with_suffix(".funscript")
    write_funscript(beside, synthesize_actions(2.0, hz=1.0))

    assert funscript_of(video, output_dir=tmp_path) == beside
    assert read_actions(funscript_of(video, output_dir=tmp_path))


def test_an_evolver_upscale_has_the_script_of_the_video_it_was_made_from(tmp_path):
    script = tmp_path / "output" / "funscript" / "clip.funscript"
    script.parent.mkdir(parents=True)
    script.write_text("{}", encoding="utf-8")
    upscale = (tmp_path / "upscaled_by_orientation" / "portrait" / "origenerator"
               / "clip_topaz.mp4")

    assert funscript_of(upscale, output_dir=tmp_path / "output") == script


def test_an_upscale_has_the_script_in_its_videos_own_place_before_one_under_its_name(tmp_path):
    output = tmp_path / "output"
    video = output / "video" / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    own = funscript_path_for(video, output_dir=output)
    write_funscript(own, synthesize_actions(5.0, hz=1.0))
    write_funscript(output / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0))
    upscale = (tmp_path / "upscaled_by_orientation" / "portrait" / "origenerator"
               / "clip_topaz.mp4")

    assert funscript_of(upscale, output_dir=output) == own


def test_an_upscale_of_a_webm_has_the_script_in_that_videos_own_place(tmp_path):
    output = tmp_path / "output"
    video = output / "video" / "clip.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    own = funscript_path_for(video, output_dir=output)
    write_funscript(own, synthesize_actions(5.0, hz=1.0))
    upscale = (tmp_path / "upscaled_by_orientation" / "landscape" / "origenerator"
               / "clip_topaz.mp4")

    assert funscript_of(upscale, output_dir=output) == own


def test_an_upscale_finds_the_script_still_beside_the_video_it_was_made_from(tmp_path):
    beside = tmp_path / "output" / "video" / "clip.funscript"
    beside.parent.mkdir(parents=True)
    beside.write_text("{}", encoding="utf-8")
    upscale = (tmp_path / "upscaled_by_orientation" / "landscape" / "origenerator"
               / "clip_topaz.mp4")

    assert funscript_of(upscale, output_dir=tmp_path / "output") == beside


def test_a_video_of_this_apps_own_named_like_an_upscale_keeps_its_own_script(tmp_path):
    video = tmp_path / "video" / "clip_topaz.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    own = tmp_path / "funscript" / "clip_topaz.funscript"
    own.parent.mkdir()
    own.write_text("{}", encoding="utf-8")

    assert funscript_of(video, output_dir=tmp_path) == own


def test_read_actions_passes_a_missing_script_through():
    """``funscript_of`` answers ``None`` for a clip with no script, and that goes
    straight to ``read_actions`` at every call site."""
    assert read_actions(None) == []


def test_synthesize_actions_alternates_extremes_at_half_period():
    # 1 Hz over 2 s → a half-cycle every 500 ms, starting at the floor.
    actions = synthesize_actions(2.0, hz=1.0)
    assert [a["pos"] for a in actions] == [0, 100, 0, 100, 0]
    assert [a["at"] for a in actions] == [0, 500, 1000, 1500, 2000]


def _cycles(actions):
    return (len(actions) - 1) / 2


def test_a_video_is_scripted_as_the_whole_number_of_cycles_nearest_the_rate_whatever_its_length():
    speed_50 = bpm_for_speed(50) / 60

    assert [_cycles(synthesize_actions(frames / NATIVE_FPS, hz=speed_50))
            for frames in (29, 81, 161, 241)] == [1, 2, 5, 7]


def test_a_scripted_video_moves_at_the_pace_the_robot_hands_speed_dial_rests_at():
    cycles_a_minute = MOTION_DEFAULT_HZ * 60
    assert cycles_a_minute == pytest.approx(bpm_for_speed(RobotHandState().speed))


def test_every_script_is_back_where_it_began_exactly_as_its_video_ends():
    duration = 49 / 16  # three and a half cycles at 1.2 Hz, were they not fitted
    actions = synthesize_actions(duration, hz=1.2)
    assert actions[0]["pos"] == actions[-1]["pos"]
    assert actions[-1]["at"] == round(duration * 1000)


def test_a_video_shorter_than_one_cycle_at_the_rate_still_gets_a_whole_one():
    actions = synthesize_actions(0.5, hz=0.5)
    assert [a["pos"] for a in actions] == [0, 100, 0]
    assert [a["at"] for a in actions] == [0, 250, 500]


def test_synthesize_actions_empty_for_nonpositive_inputs():
    assert synthesize_actions(0.0, hz=1.0) == []
    assert synthesize_actions(2.0, hz=0.0) == []


def test_write_then_read_round_trips_actions(tmp_path):
    dest = tmp_path / "clip.funscript"
    actions = synthesize_actions(2.0, hz=1.0)
    write_funscript(dest, actions)
    assert dest.exists()
    assert read_actions(dest) == actions


def test_a_script_that_is_missing_or_will_not_read_holds_no_actions(tmp_path):
    """One answer across the family, where this app answered None, a sibling
    answered an empty list and a third raised."""
    assert read_actions(tmp_path / "nope.funscript") == []
    bad = tmp_path / "bad.funscript"
    bad.write_text("not json", encoding="utf-8")
    assert read_actions(bad) == []


def test_a_script_is_written_in_its_videos_own_place_for_the_length_measured(tmp_path):
    video = tmp_path / "video" / "clip.mp4"

    dest = synthesize_funscript(video, hz=1.0, output_dir=tmp_path,
                                duration_provider=lambda _p: 2.0)

    assert dest == funscript_path_for(video, output_dir=tmp_path)
    assert read_actions(dest) == synthesize_actions(2.0, hz=1.0)


def test_a_video_of_unknown_length_gets_no_funscript(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    assert synthesize_funscript(video, hz=1.0, output_dir=tmp_path,
                                duration_provider=lambda _p: None) is None
    assert not funscript_path_for(video, output_dir=tmp_path).exists()


def _scripted_video(tmp_path, actions):
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    script = funscript_path_for(video, output_dir=tmp_path)
    write_funscript(script, actions)
    return video, script


def _synthesized_the_old_way(duration_s, hz=1.2):
    half_period = 500.0 / hz
    return [{"at": int(round(i * half_period)), "pos": 0 if i % 2 == 0 else 100}
            for i in range(int(duration_s * 1000 // half_period) + 1)]


def test_a_script_synthesized_at_another_pace_is_rewritten_at_todays(tmp_path):
    video, script = _scripted_video(tmp_path, _synthesized_the_old_way(5.0))

    rewrote = resynthesize_funscript(video, script, hz=0.5,
                                     duration_provider=lambda _p: 5.0)

    assert rewrote
    assert read_actions(script) == synthesize_actions(5.0, hz=0.5)


@pytest.mark.parametrize("authored", [
    [{"at": 0, "pos": 100}, {"at": 259, "pos": 26}, {"at": 470, "pos": 10}, {"at": 699, "pos": 83}],
    [{"at": 0, "pos": 100}, {"at": 422, "pos": 0}, {"at": 844, "pos": 100}, {"at": 1266, "pos": 0}],
    [{"at": 0, "pos": 0}, {"at": 300, "pos": 100}, {"at": 1100, "pos": 0}, {"at": 1400, "pos": 100}],
], ids=["eased to a track", "a steady motion from the top", "from the floor at an uneven pace"])
def test_a_script_that_follows_its_own_video_is_never_rewritten(tmp_path, authored):
    video, script = _scripted_video(tmp_path, authored)
    before = script.read_bytes()

    rewrote = resynthesize_funscript(video, script, hz=0.5,
                                     duration_provider=lambda _p: 5.0)

    assert not rewrote
    assert script.read_bytes() == before


def test_a_script_already_at_todays_pace_is_not_written_again(tmp_path):
    video, script = _scripted_video(tmp_path, synthesize_actions(5.0, hz=0.5))

    assert not resynthesize_funscript(video, script, hz=0.5,
                                      duration_provider=lambda _p: 5.0)


def test_a_script_whose_video_will_not_say_how_long_it_is_keeps_the_pace_it_has(tmp_path):
    video, script = _scripted_video(tmp_path, _synthesized_the_old_way(5.0))
    before = script.read_bytes()

    assert not resynthesize_funscript(video, script, hz=0.5,
                                      duration_provider=lambda _p: None)
    assert script.read_bytes() == before


# --- heatmap: funscript actions -> one color per time bucket ----------------

def test_heatmap_colors_empty_without_actions_or_buckets():
    assert heatmap_colors([], 10) == []
    assert heatmap_colors(synthesize_actions(2.0, hz=1.0), 0) == []


def test_the_heatmap_has_one_color_for_every_bucket_it_draws():
    colors = heatmap_colors(synthesize_actions(2.0, hz=1.0), 8)
    assert len(colors) == 8
    for c in colors:
        assert len(c) == 3 and all(0 <= ch <= 255 for ch in c)


def test_heatmap_colors_run_hotter_with_travel_speed():
    # A whole motion crammed into 100 ms reads "fast" (red-dominant); the same
    # motion spread over a second reads "slow" (blue-dominant). One bucket each.
    fast = heatmap_colors([{"at": 0, "pos": 0}, {"at": 100, "pos": 100}], 1)[0]
    slow = heatmap_colors([{"at": 0, "pos": 0}, {"at": 1000, "pos": 100}], 1)[0]
    assert fast[0] > fast[2]  # red > blue
    assert slow[2] > slow[0]  # blue > red
