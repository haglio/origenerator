from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from origenerator.db import Database
from origenerator.record_repair import repair_records

GRAPH = {"3": {"class_type": "KSampler", "inputs": {"seed": 7}}}
OTHER_GRAPH = {"3": {"class_type": "KSampler", "inputs": {"seed": 8}}}


def _picture(output_dir: Path, name: str, graph: dict | None = GRAPH) -> Path:
    path = output_dir / "image" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngInfo()
    if graph is not None:
        info.add_text("prompt", json.dumps(graph))
    Image.new("RGB", (8, 8)).save(path, pnginfo=info)
    return path


def _row(db: Database, prompt_id: str, *, filename: str | None = None,
         graph: dict = GRAPH, status: str = "completed",
         source: str = "generated", **fields) -> None:
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}",
                         workflow_json=json.dumps(graph), source=source)
    updates = {"status": status, **fields}
    if filename is not None:
        updates["output_files"] = json.dumps(
            [{"filename": filename, "subfolder": "image", "type": "output"}])
    db.update_generation(prompt_id, **updates)


def _ids(db: Database) -> set[str]:
    return {row["prompt_id"] for row in db.list_generations()}


def test_of_two_records_of_one_picture_the_one_whose_graph_it_carries_stays(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00001_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "made-it", filename="sdxl_t2i_00001_.png", graph=GRAPH)
    _row(db, "answered-from-cache", filename="sdxl_t2i_00001_.png", graph=OTHER_GRAPH)

    assert repair_records(db, output_dir) == 1

    assert _ids(db) == {"made-it"}


def test_the_earliest_record_stays_when_every_one_of_them_ran_the_same_graph(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00002_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00002_.png")
    _row(db, "sent-again", filename="sdxl_t2i_00002_.png")

    assert repair_records(db, output_dir) == 1

    assert _ids(db) == {"first"}


def test_a_folded_record_waits_in_the_trash_with_its_picture_left_alone(tmp_path):
    output_dir = tmp_path / "output"
    picture = _picture(output_dir, "sdxl_t2i_00003_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00003_.png")
    _row(db, "repeat", filename="sdxl_t2i_00003_.png")

    repair_records(db, output_dir)

    (held,) = db.list_deletions()
    assert held["prompt_id"] == "repeat"
    assert held["batch"] == {"moves": [], "subdir": None}
    assert picture.exists()


def test_a_star_on_the_folded_record_stays_with_the_picture(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00004_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00004_.png")
    _row(db, "repeat", filename="sdxl_t2i_00004_.png")
    db.set_generation_favorite("repeat", True)

    repair_records(db, output_dir)

    assert db.get_generation("first")["starred"] == 1


def test_the_better_versions_of_the_folded_record_stay_with_the_picture(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00005_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00005_.png")
    _row(db, "repeat", filename="sdxl_t2i_00005_.png")
    levels = json.dumps([{"filename": "image_enhance_00009_.png", "denoise": 0.3}])
    db.update_generation("repeat", enhance_history=levels,
                         original_files=json.dumps([{"filename": "sdxl_t2i_00005_.png",
                                                     "subfolder": "image"}]))

    repair_records(db, output_dir)

    kept = db.get_generation("first")
    assert json.loads(kept["enhance_history"]) == json.loads(levels)
    assert json.loads(kept["original_files"])[0]["filename"] == "sdxl_t2i_00005_.png"


def test_a_version_run_aimed_at_the_folded_record_follows_the_picture(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00006_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00006_.png")
    _row(db, "repeat", filename="sdxl_t2i_00006_.png")
    _row(db, "making-a-better-one", status="running")
    db.set_enhance_target("making-a-better-one", "repeat")

    repair_records(db, output_dir)

    assert db.get_generation("making-a-better-one")["enhance_of"] == "first"


def test_a_starred_folder_keyed_from_the_folded_record_keeps_its_star(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00007_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00007_.png")
    _row(db, "repeat", filename="sdxl_t2i_00007_.png")
    db.upsert_folder_meta("sdxl_t2i/reapony/abc123", custom_name="Kept for later",
                          favorite=True, level="settings", ref_prompt_id="repeat")

    repair_records(db, output_dir)

    (bookmark,) = db.folder_meta_full()
    assert bookmark["ref_prompt_id"] == "first"


def test_a_run_that_finished_with_no_picture_is_dropped(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00008_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "made-a-picture", filename="sdxl_t2i_00008_.png")
    _row(db, "made-nothing")

    assert repair_records(db, output_dir) == 1

    assert _ids(db) == {"made-a-picture"}
    assert [held["prompt_id"] for held in db.list_deletions()] == ["made-nothing"]


def test_an_experiment_you_turned_down_keeps_its_record(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00009_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "turned-down", source="experiment")
    db.set_experiment_verdict("turned-down", "down")

    assert repair_records(db, output_dir) == 0

    assert _ids(db) == {"turned-down"}


def test_a_record_whose_picture_is_gone_from_its_folder_is_dropped(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00010_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "still-there", filename="sdxl_t2i_00010_.png")
    _row(db, "picture-gone", filename="sdxl_t2i_00011_.png")

    assert repair_records(db, output_dir) == 1

    assert _ids(db) == {"still-there"}
    assert [held["prompt_id"] for held in db.list_deletions()] == ["picture-gone"]


def test_no_record_goes_when_the_folder_its_picture_lived_in_is_not_there(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "video").mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(output_dir / "video" / "thumb.png")
    db = Database(tmp_path / "test.db")
    _row(db, "library-not-mounted", filename="sdxl_t2i_00012_.png")

    assert repair_records(db, output_dir) == 0

    assert _ids(db) == {"library-not-mounted"}


def test_a_run_still_going_keeps_its_record(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00013_.png")
    db = Database(tmp_path / "test.db")
    for status in ("pending", "running", "error"):
        _row(db, f"{status}-run", status=status)

    assert repair_records(db, output_dir) == 0

    assert _ids(db) == {"pending-run", "running-run", "error-run"}


def test_a_second_pass_over_a_repaired_library_finds_nothing_to_do(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00014_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "first", filename="sdxl_t2i_00014_.png")
    _row(db, "repeat", filename="sdxl_t2i_00014_.png")
    _row(db, "made-nothing")

    assert repair_records(db, output_dir) == 2

    assert repair_records(db, output_dir) == 0


def test_a_record_that_lists_its_picture_twice_lists_it_once(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00015_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "listed-twice", filename="sdxl_t2i_00015_.png")
    twice = json.loads(db.get_generation("listed-twice")["output_files"]) * 2
    db.update_generation("listed-twice", output_files=json.dumps(twice))

    assert repair_records(db, output_dir) == 1

    kept = json.loads(db.get_generation("listed-twice")["output_files"])
    assert [entry["filename"] for entry in kept] == ["sdxl_t2i_00015_.png"]


def test_a_record_that_also_holds_a_picture_of_its_own_keeps_it_and_stays(tmp_path):
    output_dir = tmp_path / "output"
    _picture(output_dir, "sdxl_t2i_00016_.png")
    _picture(output_dir, "image_enhance_00016_.png")
    db = Database(tmp_path / "test.db")
    _row(db, "made-the-enhanced-one", filename="image_enhance_00016_.png")
    _row(db, "its-name-was-reused", filename="image_enhance_00016_.png")
    db.update_generation("its-name-was-reused", output_files=json.dumps([
        {"filename": "image_enhance_00016_.png", "subfolder": "image"},
        {"filename": "sdxl_t2i_00016_.png", "subfolder": "image"}]))

    assert repair_records(db, output_dir) == 1

    assert _ids(db) == {"made-the-enhanced-one", "its-name-was-reused"}
    kept = json.loads(db.get_generation("its-name-was-reused")["output_files"])
    assert [entry["filename"] for entry in kept] == ["sdxl_t2i_00016_.png"]
