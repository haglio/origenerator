"""The Trash — what the collection sees, and what the launch reclaims."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from origenerator import trash_collection
from origenerator.db import Database
from origenerator.db_connection import SqliteFile
from origenerator.trash import Trash

_NOW = datetime(2026, 8, 15, 3, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _record(prompt_id="p1", *, deleted_at=_NOW, row=None, batch=None):
    """One trashed item, shaped the way Database.list_trashed returns it."""
    return {
        "prompt_id": prompt_id,
        "row": row if row is not None else {"prompt_id": prompt_id},
        "batch": batch if batch is not None else {"moves": [], "subdir": None},
        "deleted_at": deleted_at.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(deleted_at, datetime) else deleted_at,
    }


def _file(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- how long it has been sitting there ------------------------------------


def test_a_fresh_delete_has_been_in_the_trash_no_days_at_all():
    # Rounded down: "I trashed this an hour ago" is not a day in the trash.
    assert trash_collection.days_held(_record(deleted_at=_NOW - timedelta(hours=5)), _NOW) == 0


def test_time_in_the_trash_counts_up_by_the_day():
    aged = _record(deleted_at=_NOW - timedelta(days=3, hours=2))
    assert trash_collection.days_held(aged, _NOW) == 3


def test_an_undateable_record_reads_as_freshly_deleted():
    assert trash_collection.days_held(_record(deleted_at="not a date"), _NOW) == 0


# --- what the collection draws ---------------------------------------------


def test_a_trash_item_is_the_deleted_row_plus_when_it_was_deleted():
    row = {"prompt_id": "p1", "workflow_name": "sdxl_t2i", "starred": 1,
           "output_files": json.dumps([{"filename": "a.png", "subfolder": ""}])}
    (item,) = trash_collection.trash_items([_record(row=row)], _NOW)

    assert item["workflow_name"] == "sdxl_t2i"   # still the row it always was
    assert item["starred"] == 1
    assert item["deleted_at"]
    assert "days_left" not in item   # nothing counts down; it stays until told


def test_a_trash_items_thumbnail_points_at_where_the_file_actually_is():
    # The tile has to draw something, and the delete moved the thumbnail into
    # the trash — the row's own path leads nowhere now.
    original, trashed = r"C:\thumbs\p1.jpg", r"C:\state\trash\abc\1_p1.jpg"
    record = _record(
        row={"prompt_id": "p1", "thumbnail_path": original},
        batch={"moves": [[original, trashed]], "subdir": r"C:\state\trash\abc"},
    )
    (item,) = trash_collection.trash_items([record], _NOW)
    assert item["thumbnail_path"] == trashed


def test_a_trash_item_keeps_its_path_when_the_delete_moved_nothing():
    # A delete whose files were already gone moved nothing, so there is nothing to re-point.
    record = _record(row={"prompt_id": "p1", "thumbnail_path": r"C:\thumbs\p1.jpg"})
    (item,) = trash_collection.trash_items([record], _NOW)
    assert item["thumbnail_path"] == r"C:\thumbs\p1.jpg"


def test_a_trash_items_output_files_point_at_where_they_actually_are():
    # What makes a deleted item as watchable as any other: its video is in the
    # trash, so the row that plays it has to say so.
    trashed = r"C:\state\trash\abc\0_clip.mp4"
    record = _record(
        row={"prompt_id": "p1",
             "output_files": json.dumps([{"filename": "clip.mp4", "subfolder": "video"}])},
        batch={"moves": [[r"C:\out\video\clip.mp4", trashed]], "subdir": r"C:\state\trash\abc"},
    )
    (item,) = trash_collection.trash_items([record], _NOW)
    (f,) = json.loads(item["output_files"])

    assert f["path"] == trashed
    # And it still says what the generation produced — the name the info pane
    # shows and the copy button hands over is the file's own, not the trash's.
    assert (f["filename"], f["subfolder"]) == ("clip.mp4", "video")


def test_a_trash_items_output_files_stay_put_when_the_delete_moved_nothing():
    record = _record(row={
        "prompt_id": "p1",
        "output_files": json.dumps([{"filename": "a.png", "subfolder": ""}]),
    })
    (item,) = trash_collection.trash_items([record], _NOW)
    (f,) = json.loads(item["output_files"])
    assert "path" not in f


def test_a_trash_item_says_how_long_it_has_been_in_the_trash():
    record = _record(deleted_at=_NOW - timedelta(days=4))
    (item,) = trash_collection.trash_items([record], _NOW)
    assert item["days_in_trash"] == 4


def test_trash_items_keeps_the_order_it_was_given():
    items = trash_collection.trash_items([_record("p2"), _record("p1")], _NOW)
    assert [i["prompt_id"] for i in items] == ["p2", "p1"]


# --- restoring and ending one ----------------------------------------------


def test_restore_puts_the_row_and_its_files_back(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    row = db.get_generation("p1")
    source = _file(tmp_path / "out" / "a.png", b"data")
    batch = Trash(tmp_path / "trash").store([source])
    db.delete_generation("p1")
    db.record_trashed("p1", row, batch.record())

    assert trash_collection.restore(db, db.get_trashed("p1")) == "p1"

    assert db.get_generation("p1") == row
    assert source.read_bytes() == b"data"
    assert db.get_trashed("p1") is None


def test_a_restored_item_whose_file_name_a_newer_image_took_lists_its_new_name(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    db.update_generation("p1", output_files=json.dumps(
        [{"filename": "alpha_t2i_00005_.png", "subfolder": "image"}]))
    row = db.get_generation("p1")
    image = _file(tmp_path / "out" / "alpha_t2i_00005_.png", b"deleted")
    batch = Trash(tmp_path / "trash").store([image])
    db.delete_generation("p1")
    db.record_trashed("p1", row, batch.record())
    _file(image, b"newer")

    trash_collection.restore(db, db.get_trashed("p1"))

    assert json.loads(db.get_generation("p1")["output_files"]) == [
        {"filename": "alpha_t2i_00006_.png", "subfolder": "image"}]
    assert image.read_bytes() == b"newer"


def test_purge_takes_the_held_files_and_forgets_the_record(tmp_path):
    db = Database(tmp_path / "test.db")
    batch = Trash(tmp_path / "trash").store([_file(tmp_path / "out" / "a.png")])
    db.record_trashed("p1", {"prompt_id": "p1"}, batch.record())

    trash_collection.purge(db, db.get_trashed("p1"))

    assert not batch.subdir.exists()
    assert db.get_trashed("p1") is None


# --- what the launch reclaims ----------------------------------------------


def test_the_launch_reclaims_a_batch_no_record_names(tmp_path):
    # A rejected experiment's batch that fell off the undo stack, or one left by
    # a crash between the move and the record: nothing can reach it, and nothing
    # else would ever clear it.
    db = Database(tmp_path / "test.db")
    trash = Trash(tmp_path / "trash")
    held = trash.store([_file(tmp_path / "out" / "held.png")])
    orphan = trash.store([_file(tmp_path / "out" / "orphan.png")])
    db.record_trashed("held", {"prompt_id": "held"}, held.record())

    assert trash_collection.reclaim_orphans(db, trash) == 1

    assert held.subdir.exists()
    assert not orphan.subdir.exists()


def test_the_launch_never_takes_a_trashed_item_however_old(tmp_path):
    # The whole point of holding forever: age is not a reason to destroy
    # anything. An item trashed two years ago is as recoverable as one trashed a
    # minute ago, and only the user ends it.
    db = Database(tmp_path / "test.db")
    trash = Trash(tmp_path / "trash")
    ancient = trash.store([_file(tmp_path / "out" / "ancient.png")])
    db.record_trashed("ancient", {"prompt_id": "ancient"}, ancient.record())
    _age(db, "ancient", 730)

    assert trash_collection.reclaim_orphans(db, trash) == 0

    assert [r["prompt_id"] for r in db.list_trashed()] == ["ancient"]
    assert ancient.subdir.exists()


def test_reclaiming_with_an_empty_trash_is_a_harmless_noop(tmp_path):
    db = Database(tmp_path / "test.db")
    assert trash_collection.reclaim_orphans(db, Trash(tmp_path / "trash")) == 0


def _age(db: Database, prompt_id: str, days: int):
    """Back-date a trashed item, without a fixture that has to sit around."""
    stamp = (trash_collection._now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with SqliteFile(db.path).connect() as conn:
        conn.execute("UPDATE deletions SET deleted_at = ? WHERE prompt_id = ?",
                     (stamp, prompt_id))


def test_a_stored_record_survives_the_round_trip_through_the_database(tmp_path):
    # The whole promise rests on this: a session that never performed the delete
    # can still put it back, because the row and the moves were written down.
    db = Database(tmp_path / "test.db")
    source = _file(tmp_path / "out" / "a.png", b"data")
    batch = Trash(tmp_path / "trash").store([source])
    db.record_trashed("p1", {"prompt_id": "p1", "seed": 7}, batch.record())

    reopened = Database(tmp_path / "test.db")
    (record,) = reopened.list_trashed()

    assert record["row"] == {"prompt_id": "p1", "seed": 7}
    assert [tuple(m) for m in record["batch"]["moves"]] == [
        (str(source), str(batch.moves[0][1]))
    ]
    assert Path(record["batch"]["subdir"]) == batch.subdir
