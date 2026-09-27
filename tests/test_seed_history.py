"""The seeds a Generate tab's Seed dropdown offers: every seed the library has
used, newest first, each beside a picture of the item it made.

Fixture rows are fabricated (see CLAUDE.md).
"""
from __future__ import annotations

import json

from PIL import Image

from origenerator.db import Database
from origenerator.seed_history import SeedUse, seed_history
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import WorkflowTemplate


def _row(prompt_id, **params):
    return {
        "seed": params.get("seed"),
        "params_json": json.dumps(params),
        "output_files": json.dumps([{"filename": f"{prompt_id}.png"}]),
        "thumbnail_path": f"thumbs/{prompt_id}.jpg",
    }


def test_the_seeds_come_newest_first_each_beside_the_item_it_made():
    rows = [_row("g3", seed=30), _row("g2", seed=20), _row("g1", seed=10)]

    assert seed_history(rows, "seed") == [
        SeedUse(30, "thumbs/g3.jpg"),
        SeedUse(20, "thumbs/g2.jpg"),
        SeedUse(10, "thumbs/g1.jpg"),
    ]


def test_a_seed_used_again_is_listed_each_time_beside_what_it_made_that_time():
    rows = [_row("g3", seed=10), _row("g2", seed=20), _row("g1", seed=10)]

    assert seed_history(rows, "seed") == [
        SeedUse(10, "thumbs/g3.jpg"),
        SeedUse(20, "thumbs/g2.jpg"),
        SeedUse(10, "thumbs/g1.jpg"),
    ]


def test_a_clip_offers_its_seed_to_every_seed_field_and_its_sound_seed_to_sound_seeds():
    rows = [_row("v1", noise_seed=11, audio_seed=33), _row("g1", seed=10)]

    assert seed_history(rows, "seed") == seed_history(rows, "noise_seed") == [
        SeedUse(11, "thumbs/v1.jpg"),
        SeedUse(10, "thumbs/g1.jpg"),
    ]
    assert seed_history(rows, "audio_seed") == [SeedUse(33, "thumbs/v1.jpg")]


def test_a_video_is_listed_by_the_seed_its_seed_field_holds_not_its_unused_second_one():
    loop = {**_row("v1", seed=0, noise_seed=123), "workflow_name": "wan22_flf2v_loop"}

    assert seed_history([loop], "noise_seed") == [SeedUse(123, "thumbs/v1.jpg")]


def test_listing_a_big_librarys_seeds_never_builds_a_workflows_form(monkeypatch):
    def a_form_scan(self):
        raise AssertionError("building a form reads the model folders on disk, once per row")

    monkeypatch.setattr(WorkflowTemplate, "seed_keys", a_form_scan)
    rows = [{**_row(f"v{n}", seed=0, noise_seed=n + 1), "workflow_name": "wan22_i2v"}
            for n in range(5000)]

    assert len(seed_history(rows, "noise_seed")) == 5000


def test_a_run_that_ended_having_made_nothing_offers_no_seed_of_its_own():
    failed = {**_row("g3", seed=30), "output_files": None, "status": "error"}
    emptied = {**_row("g2", seed=20), "output_files": "[]", "status": "completed"}

    assert seed_history([failed, emptied, _row("g1", seed=10)], "seed") == [
        SeedUse(10, "thumbs/g1.jpg"),
    ]


def test_a_run_in_flight_is_listed_with_no_picture_yet_at_the_size_it_will_be():
    running = {**_row("g2", seed=20, width=832, height=1216),
               "output_files": None, "status": "running"}

    assert seed_history([running, _row("g1", seed=10)], "seed") == [
        SeedUse(20, None, (832, 1216)),
        SeedUse(10, "thumbs/g1.jpg"),
    ]


def test_a_clip_in_flight_is_sized_by_the_frame_it_starts_from(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (400, 800)).save(frame)
    params = {"noise_seed": 5, "input_image": str(frame)}
    running = {**_row("v1", **params), "workflow_name": "wan22_i2v",
               "output_files": None, "status": "running"}
    derived = WORKFLOW_REGISTRY["wan22_i2v"].derived_display_size(params)

    assert derived is not None
    assert seed_history([running], "noise_seed") == [SeedUse(5, None, derived)]


def test_the_library_hands_over_every_generation_newest_first(tmp_path):
    db = Database(tmp_path / "test.db")
    for seed in (10, 20):
        prompt_id = f"gen-{seed}"
        db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                             workflow_version="v002", seed=seed,
                             params_json=json.dumps({"seed": seed}), workflow_json="{}")
        db.update_generation(prompt_id, status="completed",
                             output_files=json.dumps([{"filename": f"{prompt_id}.png"}]),
                             thumbnail_path=f"thumbs/{prompt_id}.jpg")

    assert seed_history(db.seed_history_rows(), "seed") == [
        SeedUse(20, "thumbs/gen-20.jpg"),
        SeedUse(10, "thumbs/gen-10.jpg"),
    ]


def test_a_seed_drawn_and_never_generated_is_listed_with_no_picture_at_its_size(tmp_path):
    db = Database(tmp_path / "test.db")

    db.record_seed_use(kind="drawn", seed_key="seed", seed=77, width=832, height=1216)

    assert seed_history(db.seed_history_rows(), "seed", db.list_seed_uses()) == [
        SeedUse(77, None, (832, 1216)),
    ]


def _record(seed, created_at, *, kind="drawn", seed_key="seed", thumbnail_path=None):
    return {"kind": kind, "seed_key": seed_key, "seed": seed, "width": None, "height": None,
            "thumbnail_path": thumbnail_path, "created_at": created_at}


def test_seeds_drawn_and_seeds_used_come_in_the_order_they_happened():
    rows = [{**_row("g2", seed=20), "created_at": "2026-09-26 00:00:03"},
            {**_row("g1", seed=10), "created_at": "2026-09-26 00:00:01"}]
    records = [_record(40, "2026-09-26 00:00:04"), _record(30, "2026-09-26 00:00:02")]

    assert [use.seed for use in seed_history(rows, "seed", records)] == [40, 20, 30, 10]


def test_a_seed_drawn_for_the_sound_is_offered_only_where_sound_seeds_go():
    records = [_record(50, "2026-09-26 00:00:02", seed_key="audio_seed"),
               _record(40, "2026-09-26 00:00:01", seed_key="noise_seed")]

    assert [use.seed for use in seed_history([], "seed", records)] == [40]
    assert [use.seed for use in seed_history([], "audio_seed", records)] == [50]


def test_a_drawn_seed_that_went_on_to_be_generated_is_listed_once_as_what_it_made():
    rows = [{**_row("g1", seed=40), "created_at": "2026-09-26 00:00:05"}]
    records = [_record(40, "2026-09-26 00:00:04")]

    assert seed_history(rows, "seed", records) == [SeedUse(40, "thumbs/g1.jpg")]


def test_a_stopped_run_stays_listed_beside_its_last_frame_after_its_seed_is_used_again():
    records = [_record(40, "2026-09-26 00:00:05", kind="canceled", thumbnail_path="thumbs/c.jpg"),
               _record(40, "2026-09-26 00:00:04")]
    rows = [{**_row("g1", seed=40), "created_at": "2026-09-26 00:00:06"}]

    assert seed_history(rows, "seed", records) == [
        SeedUse(40, "thumbs/g1.jpg"),
        SeedUse(40, "thumbs/c.jpg"),
    ]
