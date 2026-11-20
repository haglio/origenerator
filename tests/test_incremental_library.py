from __future__ import annotations

import copy
import json

from origenerator import gallery
from origenerator.item_names import ItemNames
from origenerator.library_views import LibrarySnapshot
from tests.real_db import database_in

_SCENES = ("a red kite", "a blue boat", "a green hill")


def _image(prompt_id: str, n: int, *, status: str = "completed") -> dict:
    return {
        "id": n, "prompt_id": prompt_id, "workflow_name": "sdxl_t2i", "workflow_version": "v1",
        "status": status, "source": "generated", "seed": n, "created_at": f"2026-01-{n % 28 + 1:02d}",
        "params_json": json.dumps({"positive_prompt": _SCENES[n % 3], "seed": n % 4}),
        "output_files": (json.dumps([{"filename": f"{prompt_id}.png", "subfolder": ""}])
                         if status == "completed" else "[]"),
    }


def _video(prompt_id: str, n: int, start_frame: str) -> dict:
    return {
        "id": n, "prompt_id": prompt_id, "workflow_name": "wan22_i2v", "workflow_version": "v1",
        "status": "completed", "source": "generated", "seed": n, "created_at": f"2026-02-{n % 28 + 1:02d}",
        "params_json": json.dumps({"positive_prompt": "made up dance", "seed": n % 3,
                                   "input_image": start_frame}),
        "output_files": json.dumps([{"filename": f"{prompt_id}.mp4", "subfolder": ""}]),
    }


def _library() -> list[dict]:
    images = [_image(f"img{n}", n) for n in range(60)]
    videos = [_video(f"vid{n}", 100 + n, f"img{n % 70}.png") for n in range(40)]
    return sorted(images + videos, key=lambda row: row["id"], reverse=True)


def _changes():
    def queue_an_image_a_video_waits_on(rows):
        return [_image("late", 200, status="pending"), _video("vid-late", 201, "late.png"), *rows]

    def land_it(rows):
        return [_image("late", 200) if row["prompt_id"] == "late" else row for row in rows]

    def take_out_an_image_videos_start_from(rows):
        return [row for row in rows if row["prompt_id"] != "img3"]

    def star_a_video(rows):
        return [{**row, "starred": 1} if row["prompt_id"] == "vid5" else row for row in rows]

    return (queue_an_image_a_video_waits_on, land_it, take_out_an_image_videos_start_from,
            star_a_video)


def test_item_names_taken_change_by_change_are_those_taken_afresh(tmp_path):
    db = database_in(tmp_path, [])
    rows = _library()
    snapshot = LibrarySnapshot(rows)
    kept_on, afresh = ItemNames(db), ItemNames(db)
    kept_on.take(snapshot.rows, snapshot.held_rows, snapshot.image_index, snapshot.readings)
    for change in _changes():
        rows = change(rows)
        snapshot = LibrarySnapshot(rows, previous=snapshot)
        kept_on.take(snapshot.rows, snapshot.held_rows, snapshot.image_index, snapshot.readings)
        fresh = LibrarySnapshot(copy.deepcopy(rows))
        afresh.take(fresh.rows, fresh.held_rows, fresh.image_index)

        assert {row["prompt_id"]: kept_on.of(row["prompt_id"]) for row in rows} == \
            {row["prompt_id"]: afresh.of(row["prompt_id"]) for row in rows}, change.__name__
        folder_of = snapshot.readings.looking_up(
            "settings folder", gallery.settings_folder_key, snapshot.image_index)
        assert [folder_of(row) for row in snapshot.rows] == [
            gallery.settings_folder_key(row, fresh.image_index) for row in fresh.rows], (
            change.__name__)


def test_an_image_landing_works_out_again_only_the_folders_of_what_it_touches(tmp_path, monkeypatch):
    db = database_in(tmp_path, [])
    rows = _changes()[0](_library())
    snapshot = LibrarySnapshot(rows)
    names = ItemNames(db)
    names.take(snapshot.rows, snapshot.held_rows, snapshot.image_index, snapshot.readings)
    before = names.of("vid-late")
    worked_out = []
    real = gallery.settings_folder_key
    monkeypatch.setattr(gallery, "settings_folder_key",
                        lambda row, index=None: worked_out.append(row["prompt_id"]) or real(row, index))

    rows = _changes()[1](rows)
    snapshot = LibrarySnapshot(rows, previous=snapshot)
    names.take(snapshot.rows, snapshot.held_rows, snapshot.image_index, snapshot.readings)

    assert names.of("vid-late") != before, "the video waiting on the image moves to its folder"
    assert sorted(worked_out) == ["late", "vid-late"], (
        "an image landing adds its frames to the image index; only the rows that look one of "
        "them up, and the row that changed, are worked out again")
