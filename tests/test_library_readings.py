from __future__ import annotations

import json

from origenerator.item_names import ItemNames
from origenerator.library_readings import LibraryReadings, read_whole
from tests.real_db import database_in, put_rows

_SHAPES = ("landscape", "portrait")


def _image(prompt_id: str) -> dict:
    return {"prompt_id": prompt_id, "status": "completed",
            "params_json": json.dumps({"positive_prompt": "scene one", "seed": 1}),
            "output_files": json.dumps([{"filename": f"{prompt_id}.png", "subfolder": ""}])}


def _readings(tmp_path, *rows):
    db = database_in(tmp_path, rows)
    published = []
    return LibraryReadings(db, ItemNames(db), published.append), db, published


def test_a_library_read_for_the_first_time_has_moved_and_read_again_has_not(tmp_path):
    readings, _db, _published = _readings(tmp_path, _image("a"))

    assert readings.moved_to(*readings.read()) is True
    assert readings.moved_to(*readings.read()) is False


def test_taking_a_read_lists_its_rows_and_publishes_their_names_once(tmp_path):
    readings, _db, published = _readings(tmp_path, _image("a"), _image("b"))
    rows, meta = readings.read()

    taken = readings.take(rows, meta, _SHAPES)
    readings.take(rows, meta, _SHAPES)

    assert sorted(row["prompt_id"] for row in taken.rows) == ["a", "b"]
    assert readings.live_ids == {"a", "b"}
    assert readings.drawn_version == 2
    assert len(published) == 1


def test_a_read_taken_before_the_gallery_redrew_is_no_news(tmp_path):
    readings, db, _published = _readings(tmp_path, _image("a"))
    stale = read_whole(db)
    read_at = readings.drawn_version
    readings.take(*readings.read(), _SHAPES)

    assert readings.is_news(stale, read_at) is False


def test_a_read_that_differs_from_the_last_one_is_news_once(tmp_path):
    readings, db, _published = _readings(tmp_path, _image("a"))
    readings.moved_to(*readings.read())
    db.set_generation_favorite("a", True)
    db.set_folder_favorite("image/sdxl_t2i", True)
    newer = read_whole(db)

    assert readings.is_news(newer, readings.drawn_version) is True
    assert readings.is_news(newer, readings.drawn_version) is False


def test_an_edit_the_gallery_made_to_a_folders_record_is_no_news_when_read_back(tmp_path):
    readings, db, _published = _readings(tmp_path, _image("a"))
    readings.take(*readings.read(), _SHAPES)
    readings.moved_to(*readings.read())
    db.set_folder_favorite("image/sdxl_t2i", True)
    readings.folder_meta["image/sdxl_t2i"] = {"custom_name": None, "starred": True}

    readings.folder_meta_edited()

    assert readings.is_news(read_whole(db), readings.drawn_version) is False


def test_a_row_is_found_among_the_listed_and_then_among_those_held_in_trash(tmp_path):
    readings, _db, _published = _readings(tmp_path, _image("a"))
    readings.take(*readings.read(), _SHAPES)

    assert readings.row_for("a")["prompt_id"] == "a"
    assert readings.row_for("nobody") is None


def _an_enhance(prompt_id: str, status: str) -> dict:
    return {"prompt_id": prompt_id, "status": status, "workflow_name": "image_enhance",
            "params_json": json.dumps({"input_image": "a.png", "seed": 2}),
            "output_files": json.dumps(
                [{"filename": f"{prompt_id}.png"}] if status == "completed" else [])}


def test_an_enhance_still_being_made_is_no_news_and_the_finished_one_is(tmp_path):
    readings, db, _published = _readings(tmp_path, _image("a"))
    readings.moved_to(*readings.read())
    put_rows(db, [_an_enhance("e1", "pending")])
    waiting = read_whole(db)
    db.update_generation("e1", status="running")
    running = read_whole(db)
    db.update_generation("e1", status="completed",
                         output_files=json.dumps([{"filename": "e1.png"}]))
    finished = read_whole(db)

    assert [readings.is_news(read, readings.drawn_version)
            for read in (waiting, running, finished)] == [False, False, True], (
        "an Enhance being made has no place in the gallery, so nothing is drawn again for it")


def test_the_leaf_folders_are_those_of_the_sides_the_last_read_was_taken_for(tmp_path):
    readings, _db, _published = _readings(tmp_path, _image("a"), _image("b"))
    assert readings.leaf_folders() == {}

    readings.take(*readings.read(), _SHAPES)

    [in_the_one_leaf] = readings.leaf_folders().values()
    assert sorted(row["prompt_id"] for row in in_the_one_leaf) == ["a", "b"]


def test_a_poll_of_an_unchanged_library_reads_none_of_its_rows_again(tmp_path, monkeypatch):
    _readings_, db, _published = _readings(tmp_path, _image("a"), _image("b"))
    last = read_whole(db)
    listed = []
    monkeypatch.setattr(db, "list_generations", lambda: listed.append(1) or [])

    assert read_whole(db, last) is last
    assert listed == []


def test_a_poll_after_any_write_reads_the_library_again(tmp_path):
    _readings_, db, _published = _readings(tmp_path, _image("a"))
    last = read_whole(db)
    db.set_generation_favorite("a", True)

    assert read_whole(db, last).rows[0]["starred"]
