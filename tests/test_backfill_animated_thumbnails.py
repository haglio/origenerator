from __future__ import annotations

import json

from PIL import Image

from origenerator import thumbnail
from origenerator.db import Database, NewGeneration
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import FRAME_MS, LONG_VIDEO_S, animated_thumbnail_path, frame_ms_of
from tests.media_files import write_mp4
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
