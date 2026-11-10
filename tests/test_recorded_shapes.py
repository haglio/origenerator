from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from origenerator import item_shape
from origenerator.completion import mark_generation_completed
from origenerator.db import Database, NewGeneration
from origenerator.gallery.shapes import LANDSCAPE, PORTRAIT
from origenerator.generation_state import GenerationStatus


@pytest.fixture
def tall_image(tmp_path):
    path = tmp_path / "made-up tall.png"
    Image.new("RGB", (9, 16)).save(path)
    return str(path)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "library.db")


def _added(db, prompt_id, *, params=None, thumbnail=None, status=GenerationStatus.COMPLETED):
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="made_up",
                                       workflow_version="v001",
                                       params_json=json.dumps(params or {}), workflow_json="{}"))
    db.update_generation(prompt_id, status=status, thumbnail_path=thumbnail)


def test_a_recorded_shape_answers_though_no_file_can_be_opened():
    assert item_shape.row_shape({"shape": PORTRAIT, "thumbnail_path": "/made-up/gone.png"}) == PORTRAIT


def test_a_row_with_no_recorded_shape_is_measured_from_its_thumbnail(tall_image):
    assert item_shape.row_shape({"thumbnail_path": tall_image}) == PORTRAIT


def test_recording_writes_each_finished_items_shape(db, tall_image):
    _added(db, "measured", thumbnail=tall_image)
    _added(db, "asked", params={"width": 1280, "height": 720})

    assert item_shape.record_shapes(db) == 2

    assert db.get_generation("measured")["shape"] == PORTRAIT
    assert db.get_generation("asked")["shape"] == LANDSCAPE


def test_the_next_launch_needs_no_file_at_all(db, tall_image):
    _added(db, "measured", thumbnail=tall_image)
    item_shape.record_shapes(db)
    Path(tall_image).unlink()

    assert item_shape.record_shapes(db) == 0
    assert item_shape.row_shape(db.get_generation("measured")) == PORTRAIT


def test_a_run_still_being_made_is_left_for_its_finished_file_to_say(db, tall_image):
    _added(db, "being made", thumbnail=tall_image, status=GenerationStatus.RUNNING)

    assert item_shape.record_shapes(db) == 0
    assert db.get_generation("being made")["shape"] is None


def test_an_item_nothing_can_measure_is_left_unrecorded(db):
    _added(db, "file gone", thumbnail="/made-up/gone.png")

    assert item_shape.record_shapes(db) == 0
    assert db.get_generation("file gone")["shape"] is None


def test_a_finished_run_records_its_shape_as_it_finishes(db, tall_image):
    _added(db, "just made", status=GenerationStatus.RUNNING)

    mark_generation_completed(db, "just made", [], tall_image, None)

    assert db.get_generation("just made")["shape"] == PORTRAIT


@pytest.mark.parametrize("change", [
    {"thumbnail_path": "/made-up/another.png"},
    {"output_files": "[]"},
])
def test_new_files_forget_the_recorded_shape(db, tall_image, change):
    _added(db, "remade", thumbnail=tall_image)
    item_shape.record_shapes(db)

    db.update_generation("remade", **change)

    assert db.get_generation("remade")["shape"] is None


def test_new_settings_forget_the_recorded_shape(db, tall_image):
    _added(db, "resized", thumbnail=tall_image)
    item_shape.record_shapes(db)

    db.set_params_json("resized", json.dumps({"width": 1280, "height": 720}))

    assert db.get_generation("resized")["shape"] is None


def test_a_library_from_before_shapes_takes_the_column_and_forgets_on_new_files(tmp_path, tall_image):
    path = tmp_path / "older"
    Database(path)
    with sqlite3.connect(path) as older:
        older.execute("DROP TRIGGER new_files_forget_the_recorded_shape")
        older.execute("ALTER TABLE generations DROP COLUMN shape")
    db = Database(path)
    _added(db, "old", thumbnail=tall_image)
    item_shape.record_shapes(db)

    db.update_generation("old", thumbnail_path="/made-up/another.png")

    assert db.get_generation("old")["shape"] is None


def test_a_favorite_keeps_the_recorded_shape(db, tall_image):
    _added(db, "starred", thumbnail=tall_image)
    item_shape.record_shapes(db)

    db.set_generation_favorite("starred", True)

    assert db.get_generation("starred")["shape"] == PORTRAIT


def test_an_unrecorded_item_is_measured_once_however_often_the_gallery_asks(tall_image, monkeypatch):
    opened = []
    real_open = Image.open
    monkeypatch.setattr(Image, "open", lambda path, *a, **kw: opened.append(path) or real_open(path, *a, **kw))
    row = {"prompt_id": "measured", "workflow_name": "made_up", "thumbnail_path": tall_image}

    shapes = [item_shape.row_shape(dict(row)) for _ in range(3)]

    assert shapes == [PORTRAIT] * 3
    assert len(opened) == 1


def test_a_file_made_again_in_another_shape_is_measured_again(tmp_path):
    path = tmp_path / "made-up.png"
    Image.new("RGB", (9, 16)).save(path)
    row = {"prompt_id": "measured", "workflow_name": "made_up", "thumbnail_path": str(path)}
    assert item_shape.row_shape(dict(row)) == PORTRAIT

    Image.new("RGB", (32, 9)).save(path)

    assert item_shape.row_shape(dict(row)) == LANDSCAPE
