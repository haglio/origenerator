"""The pass that follows an output file the user moved."""

import json

from origenerator.db import Database
from origenerator.gallery import output_file_path, resolve_preview
from origenerator.importer import import_comfyui_output
from origenerator.relocate import relocate_moved_outputs


def _library(tmp_path, rows):
    """A database holding *rows* (``prompt_id -> file records``) and an output dir."""
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
    """The move that prompted this: loose output files tidied into per-type
    subfolders, leaving every row that recorded one naming the root."""
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, output_dir) == 1

    assert _files(db, "a")[0]["subfolder"] == "image"
    assert output_file_path(_files(db, "a")[0], output_dir).is_file()


def test_it_follows_a_file_out_of_a_subfolder_too(tmp_path):
    """Nothing here is about the direction of the tidy — only about where the
    file is now versus where the row says."""
    db, output_dir = _library(tmp_path, {"a": [_file("clip.mp4", "video")]})
    (output_dir / "clip.mp4").write_bytes(b"mp4")

    assert relocate_moved_outputs(db, output_dir) == 1
    assert _files(db, "a")[0]["subfolder"] == ""


def test_a_record_that_still_resolves_is_left_untouched(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("still.png", "image")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "still.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, output_dir) == 0
    assert _files(db, "a")[0]["subfolder"] == "image"


def test_a_name_in_two_places_is_left_alone(tmp_path):
    """ComfyUI counts per filename prefix, so one name really can name two
    files. Repointing at the wrong one would show another generation's picture
    under this row's prompt, and nothing about it would look wrong."""
    db, output_dir = _library(tmp_path, {"a": [_file("wan22_i2v_00007_.mp4")]})
    for folder in ("video", "harem"):
        (output_dir / folder).mkdir()
        (output_dir / folder / "wan22_i2v_00007_.mp4").write_bytes(b"mp4")

    assert relocate_moved_outputs(db, output_dir) == 0
    assert _files(db, "a")[0]["subfolder"] == ""


def test_a_file_that_is_simply_gone_keeps_saying_where_it_was(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("deleted.png", "image")]})

    assert relocate_moved_outputs(db, output_dir) == 0
    assert _files(db, "a")[0]["subfolder"] == "image"


def test_a_file_the_recovery_bin_holds_is_not_followed(tmp_path):
    """A binned file carries an absolute ``path`` of its own — its place inside
    the trash. A copy left behind in the output tree must not pull the row back
    out of the bin."""
    trashed = tmp_path / "trash" / "held.png"
    trashed.parent.mkdir()
    trashed.write_bytes(b"png")
    db, output_dir = _library(
        tmp_path, {"a": [_file("held.png", "image", path=str(trashed))]})
    (output_dir / "held.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, output_dir) == 0
    assert _files(db, "a")[0]["path"] == str(trashed)


def test_the_pre_enhance_original_is_followed_as_well(tmp_path):
    """``original_files`` resolves through the same output dir — it is what the
    Enhance panel's level 0 offers as "what this looked like before"."""
    db, output_dir = _library(tmp_path, {"a": [_file("enhanced.png")]})
    db.update_generation("a", original_files=json.dumps([_file("before.png")]))
    (output_dir / "image").mkdir()
    for name in ("enhanced.png", "before.png"):
        (output_dir / "image" / name).write_bytes(b"png")

    assert relocate_moved_outputs(db, output_dir) == 2
    assert _files(db, "a")[0]["subfolder"] == "image"
    assert _files(db, "a", "original_files")[0]["subfolder"] == "image"


def test_it_is_idempotent(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    assert relocate_moved_outputs(db, output_dir) == 1
    assert relocate_moved_outputs(db, output_dir) == 0


def test_an_output_dir_that_is_not_there_costs_nothing(tmp_path):
    db, output_dir = _library(tmp_path, {"a": [_file("x.png")]})

    assert relocate_moved_outputs(db, tmp_path / "nowhere") == 0
    assert _files(db, "a")[0]["subfolder"] == ""
    assert output_dir.is_dir()  # the real one, untouched


def test_the_moved_file_is_not_then_imported_a_second_time(tmp_path):
    """Why this runs before the import scan. The scan keys what it has already
    seen by path under the output dir, so a file that moved reads as one it has
    never seen — and it would rebuild a bare ``imported`` row beside the
    generated row that still holds the prompt and the settings."""
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    relocate_moved_outputs(db, output_dir)

    assert import_comfyui_output(output_dir, db, tmp_path / "thumbs") == 0
    assert [r["prompt_id"] for r in db.list_generations()] == ["a"]


def test_without_it_the_scan_does_duplicate_the_row(tmp_path):
    """The other half of the pair above: the duplicate is real, so the pass is
    load-bearing rather than a tidy-up of a symptom nothing else has."""
    db, output_dir = _library(tmp_path, {"a": [_file("sdxl_t2i_00001_.png")]})
    (output_dir / "image").mkdir()
    (output_dir / "image" / "sdxl_t2i_00001_.png").write_bytes(b"png")

    assert import_comfyui_output(output_dir, db, tmp_path / "thumbs") == 1


def test_a_followed_row_previews_again(tmp_path):
    """The symptom the user sees: a row whose file moved shows its thumbnail and
    nothing else, because every surface resolves through the recorded folder."""
    db, output_dir = _library(tmp_path, {"a": [_file("clip.mp4")]})
    (output_dir / "video").mkdir()
    (output_dir / "video" / "clip.mp4").write_bytes(b"mp4")

    assert resolve_preview(_row(db, "a"), output_dir) is None

    relocate_moved_outputs(db, output_dir)

    assert resolve_preview(_row(db, "a"), output_dir) == (
        output_dir / "video" / "clip.mp4", "video")
