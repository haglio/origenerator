from __future__ import annotations

from pathlib import Path

from app_support.funscript import read_actions
from app_support.kino_folder import upscale_in
from funestra.funscript import Funscript
from funestra.heatmap import build_heatmap

from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    heatmap_colors,
)
from origenerator.output_places import OutputPlaces
from tests.funscript_files import back_and_forth_actions, write_funscript


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
                    back_and_forth_actions(2.0, hz=1.0))
    lengths = {alpha: 2.0, beta: 5.0}

    for video, seconds in lengths.items():
        write_funscript(funscript_path_for(video, places=OutputPlaces.in_one_folder(tmp_path)),
                        back_and_forth_actions(seconds, hz=1.0))

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path))) == back_and_forth_actions(
            seconds, hz=1.0)


def test_two_videos_of_one_name_in_one_folder_each_have_a_script_of_their_own(tmp_path):
    lengths = {tmp_path / "alpha" / "clip.mp4": 2.0, tmp_path / "alpha" / "clip.webm": 5.0}

    for video, seconds in lengths.items():
        write_funscript(funscript_path_for(video, places=OutputPlaces.in_one_folder(tmp_path)),
                        back_and_forth_actions(seconds, hz=1.0))

    for video, seconds in lengths.items():
        assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(tmp_path))) == back_and_forth_actions(
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
    write_funscript(beside, back_and_forth_actions(2.0, hz=1.0))

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
    write_funscript(own, back_and_forth_actions(5.0, hz=1.0))
    write_funscript(output / "funscript" / "clip.funscript",
                    back_and_forth_actions(2.0, hz=1.0))
    upscale = upscale_in(tmp_path / "kino", "portrait", "origenerator", "clip")

    assert funscript_of(upscale, places=OutputPlaces.in_one_folder(output)) == own


def test_an_upscale_of_a_webm_has_the_script_in_that_videos_own_place(tmp_path):
    output = tmp_path / "output"
    video = output / "video" / "clip.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    own = funscript_path_for(video, places=OutputPlaces.in_one_folder(output))
    write_funscript(own, back_and_forth_actions(5.0, hz=1.0))
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
    write_funscript(script, back_and_forth_actions(2.0, hz=1.0))
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
    write_funscript(own, back_and_forth_actions(5.0, hz=1.0))

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


def test_read_actions_passes_a_missing_script_through():
    assert read_actions(None) == []


def test_a_script_that_is_missing_or_will_not_read_holds_no_actions(tmp_path):
    assert read_actions(tmp_path / "nope.funscript") == []
    bad = tmp_path / "bad.funscript"
    bad.write_text("not json", encoding="utf-8")
    assert read_actions(bad) == []


def test_heatmap_colors_empty_without_actions_or_buckets_or_a_span():
    assert heatmap_colors([], 10) == []
    assert heatmap_colors([{"at": 0, "pos": 50}], 10) == []
    assert heatmap_colors(back_and_forth_actions(2.0, hz=1.0), 0) == []


def test_the_heatmap_has_one_color_for_every_bucket_it_draws():
    colors = heatmap_colors(back_and_forth_actions(2.0, hz=1.0), 8)
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
