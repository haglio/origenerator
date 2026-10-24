"""Every item in the library wears one name: its folder's code and its number there.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest

from origenerator import gallery
from origenerator.db import Database
from origenerator.item_names import ItemNames


def _picture(prompt_id: str, id_: int, prompt: str = "a red kite", **extra) -> dict:
    return {
        "id": id_, "prompt_id": prompt_id, "workflow_name": "sdxl_t2i",
        "workflow_version": "v1", "status": "completed", "source": "generated",
        "seed": id_, "params_json": json.dumps({"positive_prompt": prompt, "seed": id_}),
        "output_files": json.dumps([{"filename": f"{prompt_id}.png", "subfolder": ""}]),
        **extra,
    }


def _code(row: dict) -> str:
    return gallery.folder_id(gallery.settings_folder_key(row))


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "origenerator.db")


def test_each_item_is_named_by_its_folder_and_the_order_it_was_made_in_there(db):
    first, second = _picture("gen-one", 1), _picture("gen-two", 2)
    elsewhere = _picture("gen-three", 3, prompt="a blue kite")
    names = ItemNames(db)

    names.take([elsewhere, second, first], [], {})

    assert [names.of(row["prompt_id"]) for row in (first, second, elsewhere)] == [
        f"{_code(first)} 000", f"{_code(first)} 001", f"{_code(elsewhere)} 000"]


def test_items_brought_in_after_they_were_made_are_numbered_by_when_they_were_made(db):
    made_last = _picture("gen-one", 1, created_at="2025-06-01 00:00:00")
    made_first = _picture("gen-two", 2, created_at="2025-01-01 00:00:00")
    names = ItemNames(db)

    names.take([made_first, made_last], [], {})

    assert (names.of("gen-two"), names.of("gen-one")) == (
        f"{_code(made_first)} 000", f"{_code(made_first)} 001")


def test_an_item_keeps_its_name_after_an_older_one_is_deleted_for_good(db):
    first, second = _picture("gen-one", 1), _picture("gen-two", 2)
    ItemNames(db).take([second, first], [], {})
    after_a_restart = ItemNames(db)

    after_a_restart.take([second], [], {})

    assert after_a_restart.of("gen-two") == f"{_code(second)} 001"


def test_an_item_in_the_trash_keeps_its_place_in_the_count(db):
    trashed, kept = _picture("gen-one", 1), _picture("gen-two", 2)
    names = ItemNames(db)

    names.take([kept], [trashed], {})

    assert (names.of("gen-one"), names.of("gen-two")) == (
        f"{_code(trashed)} 000", f"{_code(kept)} 001")


def _stored(db: Database, row: dict) -> dict:
    db.insert_generation(prompt_id=row["prompt_id"], workflow_name=row["workflow_name"],
                         workflow_version=row["workflow_version"], seed=row["seed"],
                         params_json=row["params_json"], workflow_json="{}")
    db.update_generation(row["prompt_id"], status="completed", output_files=row["output_files"])
    return db.get_generation(row["prompt_id"])


def test_read_straight_from_the_database_the_trash_keeps_its_place_too(db):
    trashed = _stored(db, _picture("gen-one", 1))
    kept = _stored(db, _picture("gen-two", 2))
    db.record_deletion("gen-one", trashed, {"moves": [], "subdir": None})
    db.delete_generation("gen-one")

    names = ItemNames.from_library(db)

    assert names.of("gen-two") == f"{_code(kept)} 001"


@pytest.mark.parametrize("not_an_item", [
    {"status": "pending", "output_files": None},
    {"status": "error", "output_files": None},
    {"source": "base_render"},
], ids=["still being made", "failed", "a base render repairing a picture"])
def test_only_a_finished_item_takes_a_number(db, not_an_item):
    other, item = _picture("gen-one", 1, **not_an_item), _picture("gen-two", 2)
    names = ItemNames(db)

    names.take([item, other], [], {})

    assert (names.of("gen-one"), names.of("gen-two")) == ("", f"{_code(item)} 000")
