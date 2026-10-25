"""Folding one record of a picture into the record that stays, with no startup
pass around it: what the folded record carried goes to the one that stays.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

from origenerator.db import Database
from origenerator.record_fold import fold_record_into


def _row(db: Database, prompt_id: str, **fields) -> None:
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    if fields:
        db.update_generation(prompt_id, **fields)


def _fold_repeat_into_first(db: Database) -> None:
    fold_record_into(db, db.list_generations(), db.get_generation("repeat"),
                     db.get_generation("first"))


def _two_records(tmp_path) -> Database:
    db = Database(tmp_path / "test.db")
    _row(db, "first")
    _row(db, "repeat")
    return db


def test_a_star_on_the_folded_record_goes_to_the_one_that_stays(tmp_path):
    db = _two_records(tmp_path)
    db.set_generation_favorite("repeat", True)

    _fold_repeat_into_first(db)

    assert db.get_generation("first")["starred"] == 1


def test_the_better_versions_of_the_folded_record_go_to_the_one_that_stays(tmp_path):
    db = _two_records(tmp_path)
    levels = json.dumps([{"filename": "image_enhance_00009_.png", "denoise": 0.3}])
    originals = json.dumps([{"filename": "sdxl_t2i_00005_.png", "subfolder": "image"}])
    db.update_generation("repeat", enhance_history=levels, original_files=originals)

    _fold_repeat_into_first(db)

    kept = db.get_generation("first")
    assert (kept["enhance_history"], kept["original_files"]) == (levels, originals)


def test_a_version_run_aimed_at_the_folded_record_follows_to_the_one_that_stays(tmp_path):
    db = _two_records(tmp_path)
    _row(db, "making-a-better-one", status="running")
    db.set_enhance_target("making-a-better-one", "repeat")

    _fold_repeat_into_first(db)

    assert db.get_generation("making-a-better-one")["enhance_of"] == "first"


def test_a_starred_folder_keyed_from_the_folded_record_keeps_its_star(tmp_path):
    db = _two_records(tmp_path)
    db.upsert_folder_meta("sdxl_t2i/sample/abc123", custom_name="Kept for later",
                          favorite=True, level="settings", ref_prompt_id="repeat")

    _fold_repeat_into_first(db)

    (bookmark,) = db.folder_meta_full()
    assert bookmark["ref_prompt_id"] == "first"


def test_a_folder_of_your_own_holding_the_folded_record_holds_the_one_that_stays(tmp_path):
    db = _two_records(tmp_path)
    _row(db, "other")
    folder_id = db.create_custom_folder("Mine")
    db.add_items_to_custom_folder(folder_id, ["repeat", "other"])

    _fold_repeat_into_first(db)

    (record,) = db.list_custom_folders()
    assert record["items"] == ["first", "other"]


def test_a_folder_of_your_own_holding_both_records_holds_the_one_that_stays_once(tmp_path):
    db = _two_records(tmp_path)
    folder_id = db.create_custom_folder("Mine")
    db.add_items_to_custom_folder(folder_id, ["first", "repeat"])

    _fold_repeat_into_first(db)

    (record,) = db.list_custom_folders()
    assert record["items"] == ["first"]


def test_a_combine_made_from_the_folded_record_names_the_one_that_stays(tmp_path):
    db = _two_records(tmp_path)
    _row(db, "combined", status="running")
    db.set_recipe_source("combined", category="alpha", video_prompt_id="repeat")

    _fold_repeat_into_first(db)

    combined = db.get_generation("combined")
    assert (combined["recipe_category"], combined["recipe_video_id"]) == ("alpha", "first")
