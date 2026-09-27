from __future__ import annotations

from pathlib import Path

from app_support.funscript import read_actions

from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    heatmap_colors,
    synthesize_actions,
    synthesize_funscript,
    write_funscript,
)


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
                    synthesize_actions(2.0, hz=1.0, loop=False))
    lengths = {alpha: 2.0, beta: 5.0}

    for video in lengths:
        synthesize_funscript(video, loop=False, hz=1.0, output_dir=tmp_path,
                             duration_provider=lengths.get)

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, output_dir=tmp_path)) == synthesize_actions(
            seconds, hz=1.0, loop=False)


def test_two_videos_of_one_name_in_one_folder_each_have_a_script_of_their_own(tmp_path):
    lengths = {tmp_path / "alpha" / "clip.mp4": 2.0, tmp_path / "alpha" / "clip.webm": 5.0}

    for video in lengths:
        synthesize_funscript(video, loop=False, hz=1.0, output_dir=tmp_path,
                             duration_provider=lengths.get)

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, output_dir=tmp_path)) == synthesize_actions(
            seconds, hz=1.0, loop=False)


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
    write_funscript(beside, synthesize_actions(2.0, hz=1.0, loop=False))

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
    write_funscript(own, synthesize_actions(5.0, hz=1.0, loop=False))
    write_funscript(output / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0, loop=False))
    upscale = (tmp_path / "upscaled_by_orientation" / "portrait" / "origenerator"
               / "clip_topaz.mp4")

    assert funscript_of(upscale, output_dir=output) == own


def test_an_upscale_of_a_webm_has_the_script_in_that_videos_own_place(tmp_path):
    output = tmp_path / "output"
    video = output / "video" / "clip.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    own = funscript_path_for(video, output_dir=output)
    write_funscript(own, synthesize_actions(5.0, hz=1.0, loop=False))
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
    actions = synthesize_actions(2.0, hz=1.0, loop=False)
    assert [a["pos"] for a in actions] == [0, 100, 0, 100, 0]
    assert [a["at"] for a in actions] == [0, 500, 1000, 1500, 2000]


def test_synthesize_actions_loop_tiles_seamlessly():
    # A looping clip: the motion must return to its start position exactly at the end,
    # so it repeats without a jump as the preview loops.
    duration = 21 / 16  # flf2v default: 21 frames at 16 fps
    actions = synthesize_actions(duration, hz=1.2, loop=True)
    assert actions[0]["pos"] == actions[-1]["pos"]
    assert actions[-1]["at"] == round(duration * 1000)
    assert len(actions) % 2 == 1  # an even number of half-cycles → odd point count


def test_synthesize_actions_empty_for_nonpositive_inputs():
    assert synthesize_actions(0.0, hz=1.0, loop=False) == []
    assert synthesize_actions(2.0, hz=0.0, loop=False) == []


def test_write_then_read_round_trips_actions(tmp_path):
    dest = tmp_path / "clip.funscript"
    actions = synthesize_actions(2.0, hz=1.0, loop=False)
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

    dest = synthesize_funscript(video, loop=False, hz=1.0, output_dir=tmp_path,
                                duration_provider=lambda _p: 2.0)

    assert dest == funscript_path_for(video, output_dir=tmp_path)
    assert read_actions(dest) == synthesize_actions(2.0, hz=1.0, loop=False)


def test_a_video_of_unknown_length_gets_no_funscript(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    assert synthesize_funscript(video, loop=False, hz=1.0, output_dir=tmp_path,
                                duration_provider=lambda _p: None) is None
    assert not funscript_path_for(video, output_dir=tmp_path).exists()


# --- heatmap: funscript actions -> one color per time bucket ----------------

def test_heatmap_colors_empty_without_actions_or_buckets():
    assert heatmap_colors([], 10) == []
    assert heatmap_colors(synthesize_actions(2.0, hz=1.0, loop=False), 0) == []


def test_the_heatmap_has_one_color_for_every_bucket_it_draws():
    colors = heatmap_colors(synthesize_actions(2.0, hz=1.0, loop=False), 8)
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
