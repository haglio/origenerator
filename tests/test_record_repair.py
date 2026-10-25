from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from origenerator.db import Database
from origenerator.output_places import OutputPlaces
from origenerator.record_repair import repair_records


def _picture(output_dir: Path, name: str) -> Path:
    path = output_dir / "image" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8)).save(path)
    return path


def _row(db: Database, prompt_id: str, *, filename: str | None = None,
         status: str = "completed", source: str = "generated", **fields) -> None:
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}",
                         workflow_json="{}", source=source)
    updates = {"status": status, **fields}
    if filename is not None:
        updates["output_files"] = json.dumps(
            [{"filename": filename, "subfolder": "image", "type": "output"}])
    db.update_generation(prompt_id, **updates)


def _ids(db: Database) -> set[str]:
    return {row["prompt_id"] for row in db.list_generations()}


def test_a_run_that_finished_with_no_picture_is_dropped(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00008_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "made-a-picture", filename="sdxl_t2i_00008_.png")
    _row(db, "made-nothing")

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 1

    assert _ids(db) == {"made-a-picture"}
    assert [held["prompt_id"] for held in db.list_deletions()] == ["made-nothing"]


def test_an_experiment_you_turned_down_keeps_its_record(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00009_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "turned-down", source="experiment")
    db.set_experiment_verdict("turned-down", "down")

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 0

    assert _ids(db) == {"turned-down"}


def test_a_record_whose_picture_is_gone_from_its_folder_is_dropped(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00010_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "still-there", filename="sdxl_t2i_00010_.png")
    _row(db, "picture-gone", filename="sdxl_t2i_00011_.png")

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 1

    assert _ids(db) == {"still-there"}
    assert [held["prompt_id"] for held in db.list_deletions()] == ["picture-gone"]


def test_no_record_goes_when_the_folder_its_picture_lived_in_is_not_there(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "video").mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(output_dir / "video" / "thumb.png")
    db = Database(tmp_path / "test.db")
    _row(db, "library-not-mounted", filename="sdxl_t2i_00012_.png")

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 0

    assert _ids(db) == {"library-not-mounted"}


def test_a_run_still_going_keeps_its_record(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00013_.png")
    db = Database(tmp_path / "test.db")
    for status in ("pending", "running", "error"):
        _row(db, f"{status}-run", status=status)

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 0

    assert _ids(db) == {"pending-run", "running-run", "error-run"}


def test_a_second_pass_over_a_repaired_library_finds_nothing_to_do(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00014_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "listed-twice", filename="sdxl_t2i_00014_.png")
    twice = json.loads(db.get_generation("listed-twice")["output_files"]) * 2
    db.update_generation("listed-twice", output_files=json.dumps(twice))
    _row(db, "made-nothing")

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 2

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 0


def test_a_record_that_lists_its_picture_twice_lists_it_once(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00015_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "listed-twice", filename="sdxl_t2i_00015_.png")
    twice = json.loads(db.get_generation("listed-twice")["output_files"]) * 2
    db.update_generation("listed-twice", output_files=json.dumps(twice))

    assert repair_records(db, OutputPlaces.in_one_folder(output_dir)) == 1

    kept = json.loads(db.get_generation("listed-twice")["output_files"])
    assert [entry["filename"] for entry in kept] == ["sdxl_t2i_00015_.png"]
