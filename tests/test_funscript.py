from __future__ import annotations

import json
from pathlib import Path

import pytest
from app_support.funscript import read_actions
from app_support.kino_folder import upscale_in
from funestra.funscript import Funscript
from funestra.heatmap import build_heatmap
from funestra.robot_hand import RobotHandState, bpm_for_speed

from origenerator.config import MOTION_DEFAULT_HZ
from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    heatmap_colors,
    library_funscript_of,
    resynthesize_funscript,
    synthesize_actions,
    synthesize_funscript,
    write_funscript,
)
from origenerator.output_places import OutputPlaces
from origenerator.workflows.frame_rate import NATIVE_FPS


def test_a_script_goes_in_the_scripts_folder_under_the_folders_its_video_is_in():
    assert funscript_path_for(
        Path("/out/video/wan22_i2v_00001_.mp4"), places=OutputPlaces.in_one_folder(Path("/out"))
    ) == Path("/out/funscript/video/wan22_i2v_00001_.mp4.funscript")
    assert funscript_path_for("/out/deep/nested/clip.webm", places=OutputPlaces.in_one_folder("/out")) == Path(
        "/out/funscript/deep/nested/clip.webm.funscript")


def test_a_video_outside_the_output_dir_has_its_script_in_the_scripts_folder_itself():
    assert funscript_path_for("deep/nested/clip.webm", places=OutputPlaces.in_one_folder("/out")) == Path(
        "/out/funscript/clip.webm.funscript")


def test_two_videos_with_one_name_each_have_a_script_of_their_own(tmp_path):
    alpha = tmp_path / "alpha" / "clip.mp4"
    beta = tmp_path / "beta" / "deeper" / "clip.webm"
    write_funscript(tmp_path / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0))
    lengths = {alpha: 2.0, beta: 5.0}

    for video in lengths:
        synthesize_funscript(video, hz=1.0, places=OutputPlaces.in_one_folder(tmp_path),
                             duration_provider=lengths.get)

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path))) == synthesize_actions(
            seconds, hz=1.0)


def test_two_videos_of_one_name_in_one_folder_each_have_a_script_of_their_own(tmp_path):
    lengths = {tmp_path / "alpha" / "clip.mp4": 2.0, tmp_path / "alpha" / "clip.webm": 5.0}

    for video in lengths:
        synthesize_funscript(video, hz=1.0, places=OutputPlaces.in_one_folder(tmp_path),
                             duration_provider=lengths.get)

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path))) == synthesize_actions(
            seconds, hz=1.0)


def test_a_videos_own_script_is_found_before_those_older_versions_filed(tmp_path):
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)) is None

    beside = video.with_suffix(".funscript")
    beside.write_text("{}", encoding="utf-8")
    assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)) == beside

    filed_under_its_stem = tmp_path / "funscript" / "clip.funscript"
    filed_under_its_stem.parent.mkdir()
    filed_under_its_stem.write_text("{}", encoding="utf-8")
    assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)) == filed_under_its_stem

    own = funscript_path_for(video, places=OutputPlaces.in_one_folder(tmp_path))
    own.parent.mkdir()
    own.write_text("{}", encoding="utf-8")
    assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)) == own


def test_a_script_written_before_the_folder_existed_is_still_found(tmp_path):
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    beside = video.with_suffix(".funscript")
    write_funscript(beside, synthesize_actions(2.0, hz=1.0))

    assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)) == beside, (
        "hundreds of scripts sit beside their videos from before the scripts folder")
    assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)))


def test_an_evolver_upscale_has_the_script_of_the_video_it_was_made_from(tmp_path):
    script = tmp_path / "output" / "funscript" / "clip.funscript"
    script.parent.mkdir(parents=True)
    script.write_text("{}", encoding="utf-8")
    upscale = upscale_in(tmp_path / "kino", "portrait", "origenerator", "clip")

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(tmp_path / "output")) == script


def test_an_upscale_has_the_script_in_its_videos_own_place_before_one_under_its_name(tmp_path):
    output = tmp_path / "output"
    video = output / "video" / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    own = funscript_path_for(video, places=OutputPlaces.in_one_folder(output))
    write_funscript(own, synthesize_actions(5.0, hz=1.0))
    write_funscript(output / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0))
    upscale = upscale_in(tmp_path / "kino", "portrait", "origenerator", "clip")

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(output)) == own


def test_an_upscale_of_a_webm_has_the_script_in_that_videos_own_place(tmp_path):
    output = tmp_path / "output"
    video = output / "video" / "clip.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    own = funscript_path_for(video, places=OutputPlaces.in_one_folder(output))
    write_funscript(own, synthesize_actions(5.0, hz=1.0))
    upscale = upscale_in(tmp_path / "kino", "landscape", "origenerator", "clip")

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(output)) == own


def test_an_upscale_finds_the_script_still_beside_the_video_it_was_made_from(tmp_path):
    beside = tmp_path / "output" / "video" / "clip.funscript"
    beside.parent.mkdir(parents=True)
    beside.write_text("{}", encoding="utf-8")
    upscale = upscale_in(tmp_path / "kino", "landscape", "origenerator", "clip")

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(tmp_path / "output")) == beside, (
        "an upscale's path does not say which folder its video was kept in, so each is tried")


def _kino_upscale(library: Path) -> Path:
    upscale = library / "kino" / "2D" / "AI" / "portrait" / "example_site" / "video_one_topaz.mp4"
    upscale.parent.mkdir(parents=True)
    upscale.write_bytes(b"v")
    return upscale


def _mirrored_script_of(upscale: Path, library: Path) -> Path:
    script = (library.parent / "scripts" / "scripts" / upscale.relative_to(library)).with_suffix(".funscript")
    write_funscript(script, synthesize_actions(2.0, hz=1.0))
    return script


def test_an_upscale_with_no_script_of_this_apps_has_the_one_filed_for_it_in_the_library(tmp_path):
    library = tmp_path / "videos" / "videos"
    upscale = _kino_upscale(library)
    mirrored = _mirrored_script_of(upscale, library)

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(tmp_path / "output", library=library)) == mirrored


def test_an_upscale_keeps_this_apps_own_script_over_the_one_filed_in_the_library(tmp_path):
    library = tmp_path / "videos" / "videos"
    upscale = _kino_upscale(library)
    _mirrored_script_of(upscale, library)
    own = tmp_path / "output" / "funscript" / "video_one.funscript"
    write_funscript(own, synthesize_actions(5.0, hz=1.0))

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(tmp_path / "output", library=library)) == own


def test_an_upscale_with_no_script_filed_anywhere_has_none(tmp_path):
    library = tmp_path / "videos" / "videos"
    upscale = _kino_upscale(library)
    elsewhere = tmp_path / "elsewhere" / "landscape" / "example_site" / "video_two_topaz.mp4"

    for video in (upscale, elsewhere):
        assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path / "output", library=library)) is None


def test_an_upscale_has_no_script_from_a_library_it_was_not_told_of(tmp_path):
    library = tmp_path / "videos" / "videos"
    upscale = _kino_upscale(library)
    _mirrored_script_of(upscale, library)

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(tmp_path / "output")) is None


def test_a_video_of_this_apps_own_named_like_an_upscale_keeps_its_own_script(tmp_path):
    video = tmp_path / "video" / "clip_topaz.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    own = tmp_path / "funscript" / "clip_topaz.funscript"
    own.parent.mkdir()
    own.write_text("{}", encoding="utf-8")

    assert funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path)) == own


def test_a_library_videos_script_is_filed_in_the_scripts_tree_at_the_videos_own_place(tmp_path):
    videos = tmp_path / "videos" / "videos"
    scripts = tmp_path / "videos" / "scripts" / "scripts"
    video = videos / "2D" / "sample" / "scene one.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    filed = scripts / "2D" / "sample" / "scene one.funscript"
    write_funscript(filed, synthesize_actions(2.0, hz=1.0))

    assert library_funscript_of(video, videos_dir=videos, scripts_dir=scripts) == filed
    assert library_funscript_of(str(video).upper(), videos_dir=videos, scripts_dir=scripts) == filed


def test_a_library_video_keeps_a_script_left_beside_it(tmp_path):
    videos = tmp_path / "videos" / "videos"
    scripts = tmp_path / "videos" / "scripts" / "scripts"
    video = videos / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    write_funscript(video.with_suffix(".funscript"), synthesize_actions(2.0, hz=1.0))

    assert library_funscript_of(video, videos_dir=videos, scripts_dir=scripts) == video.with_suffix(".funscript")


def test_a_video_with_no_script_anywhere_has_none(tmp_path):
    videos = tmp_path / "videos" / "videos"
    scripts = tmp_path / "videos" / "scripts" / "scripts"
    assert library_funscript_of(videos / "clip.mp4", videos_dir=videos, scripts_dir=scripts) is None
    assert library_funscript_of(tmp_path / "elsewhere" / "clip.mp4", videos_dir=videos, scripts_dir=scripts) is None
    assert library_funscript_of("", videos_dir=videos, scripts_dir=scripts) is None


def test_read_actions_passes_a_missing_script_through():
    assert read_actions(None) == []


def test_synthesize_actions_alternates_extremes_at_half_period():
    actions = synthesize_actions(2.0, hz=1.0)
    assert [a["pos"] for a in actions] == [0, 100, 0, 100, 0]
    assert [a["at"] for a in actions] == [0, 500, 1000, 1500, 2000]


def _cycles(actions):
    return (len(actions) - 1) / 2


def test_a_video_is_scripted_as_the_whole_number_of_cycles_nearest_the_rate_whatever_its_length():
    speed_50 = bpm_for_speed(50) / 60

    assert [_cycles(synthesize_actions(frames / NATIVE_FPS, hz=speed_50))
            for frames in (29, 81, 161, 241)] == [1, 2, 5, 7]


def test_a_scripted_video_moves_at_the_pace_the_robot_hands_speed_bar_rests_at():
    cycles_a_minute = MOTION_DEFAULT_HZ * 60
    assert cycles_a_minute == pytest.approx(bpm_for_speed(RobotHandState().speed))


def test_every_script_is_back_where_it_began_exactly_as_its_video_ends():
    not_a_whole_number_of_cycles = 49 / 16
    actions = synthesize_actions(not_a_whole_number_of_cycles, hz=1.2)
    assert actions[0]["pos"] == actions[-1]["pos"]
    assert actions[-1]["at"] == round(not_a_whole_number_of_cycles * 1000)


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


def test_a_script_handed_no_video_length_records_the_length_of_its_own_span(tmp_path):
    dest = tmp_path / "clip.funscript"
    write_funscript(dest, [{"at": 0, "pos": 0}, {"at": 7400, "pos": 100}])
    assert json.loads(dest.read_text(encoding="utf-8"))["metadata"]["duration"] == 7


def test_a_script_handed_the_video_length_records_that_length_not_its_own_span(tmp_path):
    dest = tmp_path / "clip.funscript"
    write_funscript(dest, [{"at": 0, "pos": 0}, {"at": 7400, "pos": 100}], duration_seconds=12)
    assert json.loads(dest.read_text(encoding="utf-8"))["metadata"]["duration"] == 12


def test_a_script_that_is_missing_or_will_not_read_holds_no_actions(tmp_path):
    assert read_actions(tmp_path / "nope.funscript") == []
    bad = tmp_path / "bad.funscript"
    bad.write_text("not json", encoding="utf-8")
    assert read_actions(bad) == []


def test_a_script_is_written_in_its_videos_own_place_for_the_length_measured(tmp_path):
    video = tmp_path / "video" / "clip.mp4"

    dest = synthesize_funscript(video, hz=1.0, places=OutputPlaces.in_one_folder(tmp_path),
                                duration_provider=lambda _p: 2.0)

    assert dest == funscript_path_for(video, places=OutputPlaces.in_one_folder(tmp_path))
    assert read_actions(dest) == synthesize_actions(2.0, hz=1.0)


def test_a_video_of_unknown_length_gets_no_funscript(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    assert synthesize_funscript(video, hz=1.0, places=OutputPlaces.in_one_folder(tmp_path),
                                duration_provider=lambda _p: None) is None
    assert not funscript_path_for(video, places=OutputPlaces.in_one_folder(tmp_path)).exists()


def _scripted_video(tmp_path, actions):
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    script = funscript_path_for(video, places=OutputPlaces.in_one_folder(tmp_path))
    write_funscript(script, actions)
    return video, script


def _synthesized_the_old_way(duration_s, hz=1.2):
    half_period = 500.0 / hz
    return [{"at": round(i * half_period), "pos": 0 if i % 2 == 0 else 100}
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


def test_heatmap_colors_empty_without_actions_or_buckets_or_a_span():
    assert heatmap_colors([], 10) == []
    assert heatmap_colors([{"at": 0, "pos": 50}], 10) == []
    assert heatmap_colors(synthesize_actions(2.0, hz=1.0), 0) == []


def test_the_heatmap_has_one_color_for_every_bucket_it_draws():
    colors = heatmap_colors(synthesize_actions(2.0, hz=1.0), 8)
    assert len(colors) == 8
    for c in colors:
        assert len(c) == 3
        assert all(0 <= ch <= 255 for ch in c)


def test_the_heatmap_is_the_one_the_funestras_scrubber_paints():
    actions = [{"at": 0, "pos": 0}, {"at": 250, "pos": 90}, {"at": 1000, "pos": 10}]

    assert heatmap_colors(actions, 4) == build_heatmap(
        Funscript(actions=[(a["at"], a["pos"]) for a in actions]), 4, start_ms=0, end_ms=1000)


def test_heatmap_colors_run_hotter_with_travel_speed():
    fast = heatmap_colors([{"at": 0, "pos": 0}, {"at": 100, "pos": 100}], 1)[0]
    slow = heatmap_colors([{"at": 0, "pos": 0}, {"at": 1000, "pos": 100}], 1)[0]
    assert fast[0] > fast[2]
    assert slow[2] > slow[0]
