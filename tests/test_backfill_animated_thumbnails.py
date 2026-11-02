from __future__ import annotations

import json

from origenerator.db import Database, NewGeneration
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path
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
