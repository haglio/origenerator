from __future__ import annotations

import json

from PIL import Image

from origenerator import thumbnail
from origenerator.db import Database, NewGeneration
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import (
    FRAME_MS,
    LONG_VIDEO_S,
    animated_thumbnail_path,
    frame_ms_of,
    is_black,
    shows_black_among_other_frames,
)
from tests.media_files import write_mp4, write_mp4_of_shades
from tools.backfill_animated_thumbnails import main


def _library(tmp_path):
    db_path, places, thumbs = (tmp_path / "test.db", OutputPlaces.in_one_folder(tmp_path / "out"),
                               tmp_path / "thumbs")
    write_mp4(tmp_path / "out" / "scene_one.mp4")
    db = Database(db_path)
    db.insert_generation(NewGeneration(prompt_id="v1", workflow_name="wan22_i2v", workflow_version="1",
                         params_json="{}", workflow_json="{}"))
    db.update_generation("v1", status="completed", output_files=json.dumps(
        [{"filename": "scene_one.mp4", "subfolder": ""}]))
    db.insert_generation(NewGeneration(prompt_id="running", workflow_name="wan22_i2v", workflow_version="1",
                         params_json="{}", workflow_json="{}"))
    return {"db_path": db_path, "places": places, "thumb_dir": thumbs}


def test_without_apply_it_only_counts_the_videos_that_have_none(tmp_path, capsys):
    library = _library(tmp_path)

    main([], **library)

    assert "1 video(s) with no animated thumbnail" in capsys.readouterr().out
    assert not animated_thumbnail_path(library["thumb_dir"], "v1").exists()


def test_apply_makes_it_and_a_second_run_finds_nothing_left(tmp_path, capsys):
    library = _library(tmp_path)

    main(["--apply"], **library)

    assert animated_thumbnail_path(library["thumb_dir"], "v1").exists()
    capsys.readouterr()
    main([], **library)
    assert "0 video(s) with no animated thumbnail" in capsys.readouterr().out


def test_a_thumbnail_made_before_its_long_video_slowed_is_counted_and_made_again(
        tmp_path, capsys, monkeypatch):
    library = _library(tmp_path)
    frames = [Image.new("RGB", (64, 48), color) for color in ((255, 0, 0), (0, 255, 0))]
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: frames)
    main(["--apply"], **library)
    monkeypatch.setattr(thumbnail, "video_duration_seconds", lambda path: LONG_VIDEO_S + 1)
    capsys.readouterr()

    main([], **library)
    assert "1 video(s) whose animated thumbnail changes at the wrong pace" in capsys.readouterr().out

    main(["--apply"], **library)
    assert frame_ms_of(animated_thumbnail_path(library["thumb_dir"], "v1")) == 5 * FRAME_MS
    capsys.readouterr()
    main([], **library)
    assert "0 video(s) whose animated thumbnail changes at the wrong pace" in capsys.readouterr().out


def test_a_thumbnail_whose_video_never_changes_has_no_pace_to_be_wrong(tmp_path, capsys):
    library = _library(tmp_path)
    main(["--apply"], **library)
    capsys.readouterr()

    main([], **library)

    assert "0 video(s) whose animated thumbnail changes at the wrong pace" in capsys.readouterr().out


def test_a_thumbnail_made_again_stays_where_it_is_until_the_new_one_takes_its_place(
        tmp_path, monkeypatch):
    library = _library(tmp_path)
    frames = [Image.new("RGB", (64, 48), color) for color in ((255, 0, 0), (0, 255, 0))]
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: frames)
    main(["--apply"], **library)
    monkeypatch.setattr(thumbnail, "video_duration_seconds", lambda path: LONG_VIDEO_S + 1)
    there_while_remade = []

    def sampled(path, count, size):
        there_while_remade.append(animated_thumbnail_path(library["thumb_dir"], "v1").exists())
        return frames

    monkeypatch.setattr(thumbnail, "_sample_video_frames", sampled)

    main(["--apply"], **library)

    assert there_while_remade == [True]


def _made_when_black_frames_were_kept(library, tmp_path):
    write_mp4_of_shades(tmp_path / "out" / "scene_one.mp4", [0] * 8 + [200] * 24)
    thumbs = library["thumb_dir"]
    thumbs.mkdir(parents=True, exist_ok=True)
    frames = [Image.new("RGB", (16, 16), (shade, shade, shade)) for shade in (0, 200)]
    frames[0].save(animated_thumbnail_path(thumbs, "v1"), format="WEBP", save_all=True,
                   append_images=frames[1:], duration=FRAME_MS, loop=0, lossless=True)
    frames[0].save(thumbs / "v1.jpg", "JPEG")
    Database(library["db_path"]).update_generation("v1", thumbnail_path=str(thumbs / "v1.jpg"))


def test_thumbnails_showing_a_black_frame_are_counted_and_made_again_without_one(tmp_path, capsys):
    library = _library(tmp_path)
    _made_when_black_frames_were_kept(library, tmp_path)

    main([], **library)
    counted = capsys.readouterr().out
    main(["--apply"], **library)
    capsys.readouterr()
    main([], **library)

    assert "1 video(s) whose animated thumbnail shows a black frame" in counted
    assert "1 video(s) whose still thumbnail is black" in counted
    assert not shows_black_among_other_frames(animated_thumbnail_path(library["thumb_dir"], "v1"))
    assert not is_black(Image.open(library["thumb_dir"] / "v1.jpg"))
    left = capsys.readouterr().out
    assert "0 video(s) whose animated thumbnail shows a black frame" in left
    assert "0 video(s) whose still thumbnail is black" in left


def test_a_video_black_throughout_is_never_counted_as_showing_a_black_frame(tmp_path, capsys):
    library = _library(tmp_path)
    main(["--apply"], **library)
    capsys.readouterr()

    main([], **library)

    out = capsys.readouterr().out
    assert "0 video(s) whose animated thumbnail shows a black frame" in out
    assert "0 video(s) whose still thumbnail is black" in out
