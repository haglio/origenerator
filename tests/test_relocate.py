from __future__ import annotations

import json
from pathlib import Path

from app_support.funscript import read_actions

from origenerator.db import Database
from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    synthesize_actions,
    write_funscript,
)
from origenerator.gallery import output_file_path, resolve_preview
from origenerator.importer import import_comfyui_output
from origenerator.output_places import OutputPlaces
from origenerator.relocate import relocate_moved_outputs


def _library(tmp_path, rows):
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    db = Database(tmp_path / "test.db")
    for prompt_id, files in rows.items():
        db.insert_generation(
            prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="1",
            positive_prompt=None, negative_prompt=None, seed=None,
            params_json="{}", workflow_json="{}", source="generated")
        db.update_generation(prompt_id, status="completed",
                             output_files=json.dumps(files))
    return db, output_dir


def _file(name, subfolder="", **extra):
    return {"filename": name, "subfolder": subfolder, "type": "output", **extra}


def _row(db, prompt_id):
    return next(r for r in db.list_generations() if r["prompt_id"] == prompt_id)


def _files(db, prompt_id, column="output_files"):
    return json.loads(_row(db, prompt_id)[column])


def test_a_file_swept_into_a_subfolder_is_followed_there(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 1

    assert _files(db, "a")[0]["subfolder"] == "image"
    assert output_file_path(_files(db, "a")[0], OutputPlaces.in_one_folder(output_dir)).is_file()


def test_it_follows_a_file_out_of_a_subfolder_too(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("clip.mp4", "video")]})
    (output_dir / "clip.mp4").write_bytes(b"mp4")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 1
    assert _files(db, "a")[0]["subfolder"] == ""


def test_a_record_that_still_resolves_is_left_untouched(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("still.png", "image")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "still.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 0
    assert _files(db, "a")[0]["subfolder"] == "image"


def test_a_name_in_two_places_is_left_alone(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("wan22_i2v_00007_.mp4")]})
    for folder in ("video", "harem"):
        (output_dir / folder).mkdir()
        (output_dir / folder / "wan22_i2v_00007_.mp4").write_bytes(b"mp4")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 0
    assert _files(db, "a")[0]["subfolder"] == ""


def test_a_file_that_is_simply_gone_keeps_saying_where_it_was(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("deleted.png", "image")]})

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 0
    assert _files(db, "a")[0]["subfolder"] == "image"


def test_a_file_the_trash_holds_is_not_followed(tmp_path):
    trashed = tmp_path / "trash" / "held.png"
    trashed.parent.mkdir()
    trashed.write_bytes(b"png")
    db, output_dir = _library(
        tmp_path, {"a": [_file("held.png", "image", path=str(trashed))]})
    (output_dir / "held.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 0
    assert _files(db, "a")[0]["path"] == str(trashed)


def test_the_pre_enhance_original_is_followed_as_well(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("enhanced.png")]})
    db.update_generation("a", original_files=json.dumps([_file("before.png")]))
    (output_dir / "image").mkdir()
    for name in ("enhanced.png", "before.png"):
        (output_dir / "image" / name).write_bytes(b"png")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 2
    assert _files(db, "a")[0]["subfolder"] == "image"
    assert _files(db, "a", "original_files")[0]["subfolder"] == "image"


def test_it_is_idempotent(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 1
    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 0


def test_an_output_dir_that_is_not_there_costs_nothing(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("x.png")]})

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(tmp_path / "nowhere")) == 0
    assert _files(db, "a")[0]["subfolder"] == ""
    assert output_dir.is_dir()


def test_the_moved_file_is_not_then_imported_a_second_time(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir))

    assert import_comfyui_output(OutputPlaces.in_one_folder(output_dir), db, tmp_path / "thumbs") == 0
    assert [r["prompt_id"] for r in db.list_generations()] == ["a"]


def test_without_it_the_scan_does_duplicate_the_row(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    assert import_comfyui_output(OutputPlaces.in_one_folder(output_dir), db, tmp_path / "thumbs") == 1


def test_a_followed_row_previews_again(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("clip.mp4")]})
    (output_dir / "video").mkdir()
    (output_dir / "video" / "clip.mp4").write_bytes(b"mp4")

    assert resolve_preview(_row(db, "a"), OutputPlaces.in_one_folder(output_dir)) is None

    relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir))

    assert resolve_preview(_row(db, "a"), OutputPlaces.in_one_folder(output_dir)) == (
        output_dir / "video" / "clip.mp4", "video")


def test_a_moved_videos_script_moves_with_it(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("wan22_i2v_00001_.mp4", "video")]})
    was = output_dir / "video" / "wan22_i2v_00001_.mp4"
    write_funscript(funscript_path_for(was, places=OutputPlaces.in_one_folder(output_dir)),
                    synthesize_actions(2.0, hz=1.0))
    moved = output_dir / "tidied" / "wan22_i2v_00001_.mp4"
    moved.parent.mkdir()
    moved.write_bytes(b"mp4")

    relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir))

    assert read_actions(funscript_of(moved, places=OutputPlaces.in_one_folder(output_dir))) == synthesize_actions(
        2.0, hz=1.0)


def test_a_script_already_where_a_video_went_is_left_as_it_is(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("wan22_i2v_00001_.mp4", "video")]})
    write_funscript(funscript_path_for(output_dir / "video" / "wan22_i2v_00001_.mp4",
                                       places=OutputPlaces.in_one_folder(output_dir)),
                    synthesize_actions(2.0, hz=1.0))
    moved = output_dir / "tidied" / "wan22_i2v_00001_.mp4"
    moved.parent.mkdir()
    moved.write_bytes(b"mp4")
    already = funscript_path_for(moved, places=OutputPlaces.in_one_folder(output_dir))
    write_funscript(already, synthesize_actions(5.0, hz=1.0))

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 1

    assert read_actions(already) == synthesize_actions(5.0, hz=1.0)


def test_a_script_that_will_not_move_leaves_its_video_followed(tmp_path, monkeypatch):
    db, output_dir = _library(tmp_path, {"a": [_file("wan22_i2v_00001_.mp4", "video")]})
    write_funscript(funscript_path_for(output_dir / "video" / "wan22_i2v_00001_.mp4",
                                       places=OutputPlaces.in_one_folder(output_dir)),
                    synthesize_actions(2.0, hz=1.0))
    (output_dir / "tidied").mkdir()
    (output_dir / "tidied" / "wan22_i2v_00001_.mp4").write_bytes(b"mp4")

    def held_open(self, target):
        raise PermissionError("in use by another process")

    monkeypatch.setattr(Path, "rename", held_open)

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 1
    assert _files(db, "a")[0]["subfolder"] == "tidied"


def test_a_video_kept_in_the_library_is_not_followed(tmp_path):
    kept = tmp_path / "library" / "kept.mp4"
    db, output_dir = _library(
        tmp_path, {"a": [_file("kept.mp4", "video", library_path=str(kept))]})
    (output_dir / "kept.mp4").write_bytes(b"mp4")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 0
    assert _files(db, "a")[0]["subfolder"] == "video"


def test_the_enhance_history_names_files_by_name_alone_so_a_move_leaves_it_as_it_is(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("enhanced.png")]})
    history = json.dumps([_file("older.png", "gone")])
    db.update_generation("a", enhance_history=history)
    (output_dir / "image").mkdir()
    for name in ("enhanced.png", "older.png"):
        (output_dir / "image" / name).write_bytes(b"png")

    assert relocate_moved_outputs(db, OutputPlaces.in_one_folder(output_dir)) == 1
    assert _row(db, "a")["enhance_history"] == history
