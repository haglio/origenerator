from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image

from origenerator import trash_collection
from origenerator.branch_session import ENV_FLAG
from origenerator.db import Database, NewGeneration
from origenerator.db_connection import SqliteFile
from origenerator.gallery.output import resolve_preview
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

_NOW = datetime(2026, 8, 15, 3, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _record(prompt_id="p1", *, deleted_at=_NOW, row=None, batch=None):
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



def test_a_fresh_delete_has_been_in_the_trash_no_days_at_all():
    assert trash_collection.days_held(_record(deleted_at=_NOW - timedelta(hours=5)), _NOW) == 0


def test_time_in_the_trash_counts_up_by_the_day():
    aged = _record(deleted_at=_NOW - timedelta(days=3, hours=2))
    assert trash_collection.days_held(aged, _NOW) == 3


def test_an_undateable_record_reads_as_freshly_deleted():
    assert trash_collection.days_held(_record(deleted_at="not a date"), _NOW) == 0



def test_a_trash_item_is_the_deleted_row_plus_when_it_was_deleted():
    row = {"prompt_id": "p1", "workflow_name": "sdxl_t2i", "starred": 1,
           "output_files": json.dumps([{"filename": "a.png", "subfolder": ""}])}
    (item,) = trash_collection.trash_items([_record(row=row)], _NOW)

    assert item["workflow_name"] == "sdxl_t2i"
    assert item["starred"] == 1
    assert item["deleted_at"]
    assert "days_left" not in item


def test_a_trash_items_thumbnail_points_at_where_the_file_actually_is():
    original, trashed = r"C:\thumbs\p1.jpg", r"C:\state\trash\abc\1_p1.jpg"
    record = _record(
        row={"prompt_id": "p1", "thumbnail_path": original},
        batch={"moves": [[original, trashed]], "subdir": r"C:\state\trash\abc"},
    )
    (item,) = trash_collection.trash_items([record], _NOW)
    assert item["thumbnail_path"] == trashed


def test_a_trash_item_keeps_its_path_when_the_delete_moved_nothing():
    record = _record(row={"prompt_id": "p1", "thumbnail_path": r"C:\thumbs\p1.jpg"})
    (item,) = trash_collection.trash_items([record], _NOW)
    assert item["thumbnail_path"] == r"C:\thumbs\p1.jpg", (
        "a delete whose files were already gone moved nothing, so nothing is re-pointed")


def test_a_trash_items_output_files_point_at_where_they_actually_are():
    trashed = r"C:\state\trash\abc\0_clip.mp4"
    record = _record(
        row={"prompt_id": "p1",
             "output_files": json.dumps([{"filename": "clip.mp4", "subfolder": "video"}])},
        batch={"moves": [[r"C:\out\video\clip.mp4", trashed]], "subdir": r"C:\state\trash\abc"},
    )
    (item,) = trash_collection.trash_items([record], _NOW)
    (f,) = json.loads(item["output_files"])

    assert f["path"] == trashed
    assert (f["filename"], f["subfolder"]) == ("clip.mp4", "video"), (
        "the name a Generate tab shows and the copy button hands over is the file's own, "
        "never the trash's")


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



def test_restore_puts_the_row_and_its_files_back(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}"))
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
    db.insert_generation(NewGeneration(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}"))
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

    assert not batch.subdir.exists(), (
        "nothing can undo this: the row went at the delete, and these were the only copies")
    assert db.get_trashed("p1") is None



def test_the_launch_reclaims_a_batch_no_record_names(tmp_path):
    db = Database(tmp_path / "test.db")
    trash = Trash(tmp_path / "trash")
    held = trash.store([_file(tmp_path / "out" / "held.png")])
    orphan = trash.store([_file(tmp_path / "out" / "orphan.png")])
    db.record_trashed("held", {"prompt_id": "held"}, held.record())

    assert trash_collection.reclaim_orphans(db, trash) == 1

    assert held.subdir.exists()
    assert not orphan.subdir.exists(), (
        "a rejected experiment's batch that fell off the undo stack, or one a crash left "
        "between the move and the record, is reached by nothing else and cleared by nothing else")


def test_reclaiming_never_takes_a_trashed_item_however_old(tmp_path):
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
    stamp = (trash_collection._now_as_sqlite_stamps_it() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with SqliteFile(db.path).connect() as conn:
        conn.execute("UPDATE deletions SET deleted_at = ? WHERE prompt_id = ?",
                     (stamp, prompt_id))


def test_a_stored_record_survives_the_round_trip_through_the_database(tmp_path):
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


def test_an_item_deleted_restored_and_deleted_again_is_trashed_on_the_date_of_the_latest_delete(tmp_path):
    db = Database(tmp_path / "test.db")
    db.record_trashed("p1", {"prompt_id": "p1"}, {"moves": [], "subdir": None})
    _age(db, "p1", 9)
    earlier = db.get_trashed("p1")["deleted_at"]

    db.record_trashed("p1", {"prompt_id": "p1"}, {"moves": [], "subdir": None})

    assert db.get_trashed("p1")["deleted_at"] != earlier


def test_rewriting_a_held_items_record_keeps_its_date(tmp_path):
    db = Database(tmp_path / "test.db")
    db.record_trashed("p1", {"prompt_id": "p1", "seed": 1}, {"moves": [], "subdir": None})
    _age(db, "p1", 9)
    earlier = db.get_trashed("p1")["deleted_at"]

    db.record_trashed("p1", {"prompt_id": "p1", "seed": 2}, {"moves": [], "subdir": None}, deleted_at=earlier)

    held = db.get_trashed("p1")
    assert (held["deleted_at"], held["row"]["seed"]) == (earlier, 2)


def _held_item(tmp_path, db, prompt_id="p1", *, days=2):
    video = _file(tmp_path / "out" / f"{prompt_id}.mp4", b"video")
    thumb = _file(tmp_path / "thumbs" / f"{prompt_id}.jpg", b"thumb")
    row = {"prompt_id": prompt_id, "thumbnail_path": str(thumb),
           "output_files": json.dumps([{"filename": video.name, "subfolder": ""}])}
    batch = Trash(tmp_path / "trash").store([video, thumb])
    db.record_trashed(prompt_id, row, batch.record())
    _age(db, prompt_id, days)
    return batch


def _places(tmp_path):
    return OutputPlaces.in_one_folder(tmp_path / "out")


def test_a_day_in_the_trash_leaves_only_the_thumbnail(tmp_path):
    db = Database(tmp_path / "test.db")
    batch = _held_item(tmp_path, db)

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 1

    assert [path.name for path in batch.subdir.iterdir()] == ["1_p1.jpg"]
    assert trash_collection.is_emptied(db.get_trashed("p1"))


def test_an_item_deleted_less_than_a_day_ago_keeps_its_files(tmp_path):
    db = Database(tmp_path / "test.db")
    batch = _held_item(tmp_path, db, days=0)

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 0

    assert sorted(path.name for path in batch.subdir.iterdir()) == ["0_p1.mp4", "1_p1.jpg"]
    assert not trash_collection.is_emptied(db.get_trashed("p1"))


def test_emptying_leaves_when_the_item_was_deleted_as_it_was(tmp_path):
    db = Database(tmp_path / "test.db")
    _held_item(tmp_path, db)
    deleted_at = db.get_trashed("p1")["deleted_at"]

    trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path))

    assert db.get_trashed("p1")["deleted_at"] == deleted_at


def test_an_item_emptied_once_is_not_counted_again(tmp_path):
    db = Database(tmp_path / "test.db")
    _held_item(tmp_path, db)

    trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path))

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 0


def test_an_emptied_item_says_so_and_still_finds_its_thumbnail(tmp_path):
    db = Database(tmp_path / "test.db")
    batch = _held_item(tmp_path, db)

    trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path))

    item = trash_collection.trash_items(db.list_trashed())[0]
    assert item["emptied"] is True
    assert Path(item["thumbnail_path"]) == batch.subdir / "1_p1.jpg"
    assert resolve_preview(item, _places(tmp_path)) == (batch.subdir / "1_p1.jpg", MediaType.IMAGE)


def test_an_emptied_item_shows_its_thumbnail_even_where_a_newer_item_took_its_name(tmp_path):
    db = Database(tmp_path / "test.db")
    _held_item(tmp_path, db)
    trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path))
    _file(tmp_path / "out" / "p1.mp4", b"a newer video")

    item = trash_collection.trash_items(db.list_trashed())[0]

    assert resolve_preview(item, _places(tmp_path))[1] == MediaType.IMAGE


def test_an_item_with_no_thumbnail_is_given_one_before_it_is_emptied(tmp_path):
    db = Database(tmp_path / "test.db")
    image = tmp_path / "out" / "p1.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(image)
    batch = Trash(tmp_path / "trash").store([image])
    db.record_trashed("p1", {"prompt_id": "p1", "output_files": json.dumps(
        [{"filename": "p1.png", "subfolder": ""}])}, batch.record())
    _age(db, "p1", 2)

    trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path))

    item = trash_collection.trash_items(db.list_trashed())[0]
    assert not (batch.subdir / "0_p1.png").exists()
    assert Path(item["thumbnail_path"]).is_file()
    assert Path(item["thumbnail_path"]).parent == batch.subdir


def test_an_item_whose_thumbnail_cannot_be_made_keeps_its_file(tmp_path):
    db = Database(tmp_path / "test.db")
    unreadable = _file(tmp_path / "out" / "p1.png", b"not an image")
    batch = Trash(tmp_path / "trash").store([unreadable])
    db.record_trashed("p1", {"prompt_id": "p1", "output_files": json.dumps(
        [{"filename": "p1.png", "subfolder": ""}])}, batch.record())
    _age(db, "p1", 2)

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 0

    assert (batch.subdir / "0_p1.png").exists()
    assert not trash_collection.is_emptied(db.get_trashed("p1"))


def _emptied_item_being_regenerated(tmp_path, db):
    _held_item(tmp_path, db)
    trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path))
    held = db.get_trashed("p1")
    db.record_trashed("p1", {**held["row"], "workflow_name": "sdxl_t2i", "workflow_version": "v1",
                              "params_json": "{}", "workflow_json": "{}", "starred": 1},
                       held["batch"], deleted_at=held["deleted_at"])
    db.insert_generation(NewGeneration(prompt_id="job", workflow_name="sdxl_t2i", workflow_version="v1",
                         params_json="{}", workflow_json="{}"))
    trash_collection.start_regenerating(db, db.get_trashed("p1"), "job")


def test_an_item_being_regenerated_is_not_in_the_trash(tmp_path):
    db = Database(tmp_path / "test.db")
    _emptied_item_being_regenerated(tmp_path, db)

    assert trash_collection.trash_items(db.list_trashed()) == []


def test_a_job_still_running_leaves_everything_as_it_is(tmp_path):
    db = Database(tmp_path / "test.db")
    _emptied_item_being_regenerated(tmp_path, db)

    assert trash_collection.settle_regenerations(db) == 0

    assert db.get_generation("job") is not None
    assert db.get_generation("p1") is None


def test_a_finished_job_brings_the_item_back_as_itself_with_the_new_files(tmp_path):
    db = Database(tmp_path / "test.db")
    _emptied_item_being_regenerated(tmp_path, db)
    subdir = Path(db.get_trashed("p1")["batch"]["subdir"])
    new_files = json.dumps([{"filename": "new.mp4", "subfolder": ""}])
    db.update_generation("job", status="completed", output_files=new_files,
                         thumbnail_path="new.jpg")

    assert trash_collection.settle_regenerations(db) == 1

    back = db.get_generation("p1")
    assert (back["output_files"], back["thumbnail_path"], back["status"], back["starred"]) == (
        new_files, "new.jpg", "completed", 1)
    assert db.get_generation("job") is None
    assert db.get_trashed("p1") is None
    assert not subdir.exists()


def test_a_failed_job_puts_the_item_back_in_the_trash_and_leaves_no_failed_item(tmp_path):
    db = Database(tmp_path / "test.db")
    _emptied_item_being_regenerated(tmp_path, db)
    db.update_generation("job", status="error", error_message="made up")

    assert trash_collection.settle_regenerations(db) == 1

    assert db.get_generation("job") is None
    assert [item["prompt_id"] for item in trash_collection.trash_items(db.list_trashed())] == ["p1"]
    assert trash_collection.is_emptied(db.get_trashed("p1"))


def test_a_canceled_job_puts_the_item_back_in_the_trash(tmp_path):
    db = Database(tmp_path / "test.db")
    _emptied_item_being_regenerated(tmp_path, db)
    db.delete_generation("job")

    assert trash_collection.settle_regenerations(db) == 1

    assert [item["prompt_id"] for item in trash_collection.trash_items(db.list_trashed())] == ["p1"]


def _places_with_trash(tmp_path):
    return OutputPlaces.in_one_folder(tmp_path / "out", trash=tmp_path / "trash")


def test_a_launch_empties_what_has_waited_a_day_and_says_how_many(tmp_path):
    db = Database(tmp_path / "test.db")
    _held_item(tmp_path, db)

    assert trash_collection.tend_the_trash(db, _places_with_trash(tmp_path), environ={}) == 1

    assert trash_collection.is_emptied(db.get_trashed("p1"))


def test_a_preview_leaves_the_trash_as_it_is_until_the_change_ships(tmp_path):
    db = Database(tmp_path / "test.db")
    _held_item(tmp_path, db)

    assert trash_collection.tend_the_trash(db, _places_with_trash(tmp_path), environ={ENV_FLAG: "1"}) == 0

    assert not trash_collection.is_emptied(db.get_trashed("p1"))


def test_a_launch_reclaims_what_no_record_names_and_settles_what_was_being_made_again(tmp_path):
    db = Database(tmp_path / "test.db")
    _emptied_item_being_regenerated(tmp_path, db)
    db.delete_generation("job")
    orphan = Trash(tmp_path / "trash").store([_file(tmp_path / "out" / "orphan.png")])

    trash_collection.tend_the_trash(db, _places_with_trash(tmp_path), environ={})

    assert not orphan.subdir.exists()
    assert [item["prompt_id"] for item in trash_collection.trash_items(db.list_trashed())] == ["p1"]




def _held_start_image(tmp_path, db):
    image = _file(tmp_path / "out" / "frame.png", b"image")
    thumb = _file(tmp_path / "thumbs" / "frame.jpg", b"thumb")
    batch = Trash(tmp_path / "trash").store([image, thumb])
    db.record_trashed("frame", {"prompt_id": "frame", "thumbnail_path": str(thumb), "output_files":
                                 json.dumps([{"filename": "frame.png", "subfolder": ""}])},
                       batch.record())
    _age(db, "frame", 2)
    return batch


def _video_started_from_the_frame(db):
    workflow = next(name for name, template in WORKFLOW_REGISTRY.items()
                    if "input_image" in dict(template.input_params))
    db.insert_generation(NewGeneration(prompt_id="video", workflow_name=workflow, workflow_version="v1",
                         params_json=json.dumps({"input_image": "frame.png [output]"}),
                         workflow_json="{}"))


def test_the_start_image_of_a_video_in_the_library_keeps_its_file(tmp_path):
    db = Database(tmp_path / "test.db")
    batch = _held_start_image(tmp_path, db)
    _video_started_from_the_frame(db)

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 0

    assert (batch.subdir / "0_frame.png").exists()
    assert not trash_collection.is_emptied(db.get_trashed("frame"))


def test_a_start_image_is_emptied_once_its_video_has_left_the_library(tmp_path):
    db = Database(tmp_path / "test.db")
    batch = _held_start_image(tmp_path, db)
    _video_started_from_the_frame(db)
    db.delete_generation("video")

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 1

    assert not (batch.subdir / "0_frame.png").exists()


def test_an_item_whose_files_are_all_gone_is_emptied_with_no_thumbnail(tmp_path):
    db = Database(tmp_path / "test.db")
    gone = _file(tmp_path / "out" / "p1.png")
    batch = Trash(tmp_path / "trash").store([gone])
    (batch.subdir / "0_p1.png").unlink()
    db.record_trashed("p1", {"prompt_id": "p1", "output_files": json.dumps(
        [{"filename": "p1.png", "subfolder": ""}])}, batch.record())
    _age(db, "p1", 2)

    assert trash_collection.empty_what_has_waited_a_day(db, _places(tmp_path)) == 1

    assert trash_collection.trash_items(db.list_trashed())[0]["thumbnail_path"] is None
