from __future__ import annotations

import json

from origenerator import gallery, library_readings
from origenerator.item_names import ItemNames
from origenerator.library_readings import LibraryReadings, read_whole
from origenerator.workflows import WORKFLOW_REGISTRY
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


def _a_job(prompt_id: str, status: str, **params) -> dict:
    return {**_image(prompt_id), "status": status,
            "params_json": json.dumps({"positive_prompt": "scene one", "seed": 3, **params}),
            "output_files": "[]"}


def test_a_job_that_starts_running_is_no_news_and_its_queuing_and_landing_are(tmp_path):
    readings, db, _published = _readings(tmp_path, _image("a"))
    readings.moved_to(*readings.read())
    put_rows(db, [_a_job("j", "pending")])
    queued = read_whole(db)
    db.update_generation("j", status="running")
    running = read_whole(db)
    db.update_generation("j", status="completed",
                         output_files=json.dumps([{"filename": "j.png", "subfolder": ""}]))
    landed = read_whole(db)

    assert [readings.is_news(read, readings.drawn_version)
            for read in (queued, running, landed)] == [True, False, True], (
        "a job's own tile in the gallery and its line in the Job Queue say it started; the "
        "folders, the TOC and the search are the same before and after")


def test_a_waiting_job_whose_settings_change_is_news(tmp_path):
    readings, db, _published = _readings(tmp_path, _image("a"), _a_job("j", "pending"))
    readings.moved_to(*readings.read())
    db.set_params_and_workflow("j", params_json=json.dumps(
        {"positive_prompt": "scene one", "seed": 3, "start_image": "a.png"}), workflow_json="{}")

    assert readings.is_news(read_whole(db), readings.drawn_version) is True, (
        "a waiting video's settings take its starting frame when it starts, and the folder "
        "it sits in can change with them")


def test_the_leaf_folders_are_those_of_the_sides_the_last_read_was_taken_for(tmp_path):
    readings, _db, _published = _readings(tmp_path, _image("a"), _image("b"))
    assert readings.leaf_folders() == {}

    readings.take(*readings.read(), _SHAPES)

    [in_the_one_leaf] = readings.leaf_folders().values()
    assert sorted(row["prompt_id"] for row in in_the_one_leaf) == ["a", "b"]


def test_a_poll_of_an_unchanged_library_reads_none_of_its_rows_again(tmp_path, monkeypatch):
    _, db, _ = _readings(tmp_path, _image("a"), _image("b"))
    last = read_whole(db)
    listed = []
    monkeypatch.setattr(db, "list_generations", lambda: listed.append(1) or [])

    assert read_whole(db, last) is last
    assert listed == []


def test_a_poll_after_any_write_reads_the_library_again(tmp_path):
    _, db, _ = _readings(tmp_path, _image("a"))
    last = read_whole(db)
    db.set_generation_favorite("a", True)

    assert read_whole(db, last).rows[0]["starred"]


def _counting_fingerprints(monkeypatch) -> list[int]:
    counted: list[int] = []
    real = library_readings._rows_fingerprint
    monkeypatch.setattr(library_readings, "_rows_fingerprint",
                        lambda rows: counted.append(len(rows)) or real(rows))
    return counted


def test_rows_read_and_found_moved_are_not_fingerprinted_again_when_taken(tmp_path, monkeypatch):
    readings, _db, _published = _readings(tmp_path, _image("a"), _image("b"))
    counted = _counting_fingerprints(monkeypatch)
    rows, meta = readings.read()

    readings.moved_to(rows, meta)
    readings.take(rows, meta, _SHAPES)

    assert counted == [2], "the fingerprint walks every row, so a rebuild works it out once"


def test_rows_the_poll_fingerprinted_are_not_fingerprinted_again_when_taken(tmp_path, monkeypatch):
    readings, db, _published = _readings(tmp_path, _image("a"))
    read = read_whole(db)
    counted = _counting_fingerprints(monkeypatch)

    assert readings.is_news(read, readings.drawn_version) is True
    readings.take(read.rows, read.meta, _SHAPES)

    assert counted == []


def _a_start_frame_and_its_video() -> tuple[dict, dict]:
    image_workflow, video_workflow = WORKFLOW_REGISTRY["sdxl_t2i"], WORKFLOW_REGISTRY["wan22_i2v"]
    image = {"prompt_id": "img-1", "workflow_name": "sdxl_t2i",
             "workflow_version": image_workflow.version, "status": "completed",
             "params_json": json.dumps({**image_workflow.default_params(), "seed": 100}),
             "output_files": json.dumps([{"filename": "frame_001.png", "subfolder": "",
                                          "type": "output"}])}
    video = {"prompt_id": "vid-run", "workflow_name": "wan22_i2v",
             "workflow_version": video_workflow.version, "status": "running",
             "params_json": json.dumps({**video_workflow.default_params(),
                                        "input_image": "frame_001.png [output]"})}
    return image, video


def test_a_library_not_yet_read_files_a_video_by_its_start_frames_settings(tmp_path):
    image, video = _a_start_frame_and_its_video()
    readings, _db, _published = _readings(tmp_path, image, video)

    by_its_frame = gallery.settings_folder_key(video, gallery.image_config_index_of([image]))

    assert by_its_frame != gallery.settings_folder_key(video)
    assert readings.folder_keys()(video) == by_its_frame, (
        "Standalone takes its running jobs back before the gallery has read its library, so "
        "a video is filed by its start frame's settings read from the database")


def test_a_library_read_files_by_the_reading_it_holds_without_listing_again(
        tmp_path, monkeypatch):
    image, video = _a_start_frame_and_its_video()
    readings, db, _published = _readings(tmp_path, image, video)
    readings.take(*readings.read(), _SHAPES)
    listed = []
    listing = db.list_generations
    monkeypatch.setattr(db, "list_generations", lambda: listed.append(1) or listing())

    filed = readings.folder_keys()(video)

    assert filed == gallery.settings_folder_key(video, gallery.image_config_index_of([image]))
    assert listed == []
