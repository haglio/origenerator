import json
import sqlite3
from contextlib import closing

import pytest

from origenerator.db import Database


def test_schema_creates_generations_table(tmp_path):
    db = Database(tmp_path / "test.db")
    conn = sqlite3.connect(db.path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='generations'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_insert_and_get_generation(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="test-uuid-001",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        positive_prompt="a cat",
        negative_prompt="ugly",
        seed=12345,
        params_json=json.dumps({"steps": 50}),
        workflow_json=json.dumps({"1": {}}),
    )
    row = db.get_generation("test-uuid-001")
    assert row is not None
    assert row["prompt_id"] == "test-uuid-001"
    assert row["workflow_name"] == "sdxl_t2i"
    assert row["positive_prompt"] == "a cat"
    assert row["seed"] == 12345
    assert row["status"] == "pending"
    assert row["source"] == "generated"


def test_recipe_source_records_where_a_combine_got_its_recipe(tmp_path):
    # Nothing else on the row says it: the params carry the recipe's values, never
    # which video they came from or what the user called the act.
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="rec-001", workflow_name="wan22_i2v", workflow_version="v001",
        params_json="{}", workflow_json="{}",
    )
    assert db.get_generation("rec-001")["recipe_category"] is None

    db.set_recipe_source("rec-001", category="dancing", video_prompt_id="vid-9")

    row = db.get_generation("rec-001")
    assert row["recipe_category"] == "dancing"
    assert row["recipe_video_id"] == "vid-9"


def test_enhance_target_names_the_image_a_run_is_of(tmp_path):
    # The run's params name the file it reads, and a file name can belong to
    # more than one row; the stamp is the one thing on the run that names the row.
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="enh-001", workflow_name="image_enhance", workflow_version="v001",
        params_json="{}", workflow_json="{}",
    )
    assert db.get_generation("enh-001")["enhance_of"] is None

    db.set_enhance_target("enh-001", "img-007")
    assert db.get_generation("enh-001")["enhance_of"] == "img-007"

    db.set_enhance_target("enh-001", None)  # cleared, as an empty value would be
    assert db.get_generation("enh-001")["enhance_of"] is None


def test_each_half_of_a_recipe_source_can_stand_alone(tmp_path):
    # A dropped video names no act, and an act the overlay curates a recipe for is
    # answered from no past video.
    db = Database(tmp_path / "test.db")
    for pid in ("dropped", "curated"):
        db.insert_generation(prompt_id=pid, workflow_name="wan22_i2v",
                             workflow_version="v001", params_json="{}", workflow_json="{}")
    db.set_recipe_source("dropped", video_prompt_id="vid-9")
    db.set_recipe_source("curated", category="dancing")

    assert db.get_generation("dropped")["recipe_category"] is None
    assert db.get_generation("dropped")["recipe_video_id"] == "vid-9"
    assert db.get_generation("curated")["recipe_category"] == "dancing"
    assert db.get_generation("curated")["recipe_video_id"] is None


def test_update_generation(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="upd-001",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        params_json="{}",
        workflow_json="{}",
    )
    db.update_generation(
        "upd-001",
        status="completed",
        output_files=json.dumps([{"filename": "out.png"}]),
        thumbnail_path="thumbs/out.jpg",
    )
    row = db.get_generation("upd-001")
    assert row["status"] == "completed"
    assert row["output_files"] == json.dumps([{"filename": "out.png"}])
    assert row["thumbnail_path"] == "thumbs/out.jpg"


def test_update_generation_refuses_a_column_it_does_not_write(tmp_path):
    """It writes a job's lifecycle. Everything else on the row is provenance
    fixed at insert, or a user's own mark, and each of those has its own named
    method -- so a key outside the set is a caller reaching for the wrong one.
    It used to be dropped in silence, which made a typo a no-op with no error."""
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="upd-002",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        params_json="{}",
        workflow_json="{}",
    )

    with pytest.raises(ValueError) as refused:
        db.update_generation("upd-002", workflow_name="wan22_i2v")

    assert "workflow_name" in str(refused.value)
    assert db.get_generation("upd-002")["workflow_name"] == "sdxl_t2i"


def test_update_generation_with_nothing_to_write_is_a_no_op(tmp_path):
    """Callers build the field dict conditionally -- an enhance level removed
    from a row that had none yields ``{}`` -- so an empty update is a normal
    outcome rather than a mistake."""
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="upd-003",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        params_json="{}",
        workflow_json="{}",
    )

    db.update_generation("upd-003")

    assert db.get_generation("upd-003")["status"] == "pending"


def test_update_generation_stores_duration_seconds(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="dur-001",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        params_json="{}",
        workflow_json="{}",
    )
    db.update_generation("dur-001", status="completed", duration_seconds=15.26)
    row = db.get_generation("dur-001")
    assert row["duration_seconds"] == 15.26


def _database_as_first_written(db_path):
    """A database with the two tables as this app first wrote them, before any
    column was added to either — and one generation already in it.

    Every column since is patched in by ``Database._migrate``, whose whole job is
    that a user's own library, made against this schema, still opens.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE generations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " prompt_id TEXT NOT NULL UNIQUE,"
        " source TEXT NOT NULL DEFAULT 'generated',"
        " workflow_name TEXT NOT NULL,"
        " workflow_version TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
        " params_json TEXT NOT NULL,"
        " workflow_json TEXT NOT NULL,"
        " output_files TEXT, thumbnail_path TEXT, error_message TEXT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " completed_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE folder_meta ("
        " folder_key TEXT PRIMARY KEY,"
        " custom_name TEXT,"
        " starred INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "INSERT INTO generations"
        " (prompt_id, workflow_name, workflow_version, params_json, workflow_json)"
        " VALUES ('old-001', 'sdxl_t2i', 'v002', '{}', '{}')"
    )
    conn.commit()
    conn.close()
    return db_path


def _columns(db_path, table):
    # closing(), not the bare `with`: sqlite3's context manager commits and leaves
    # the connection open — the very thing origenerator.db._connect exists to fix.
    with closing(sqlite3.connect(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


# Every column the two tables have grown since. Seven of these could be dropped
# from the migration with the whole suite still green, and each one dropped is a
# user's own library failing to open on the next launch.
@pytest.mark.parametrize("column", [
    "duration_seconds", "evolver_exported_at", "genau_exported_at",
    "genau_requested_at", "progress_json", "starred", "experiment_verdict",
    "original_files", "enhance_history", "recipe_category", "recipe_video_id",
    "enhance_of",
])
def test_an_early_database_gains_every_generations_column(tmp_path, column):
    Database(_database_as_first_written(tmp_path / "old.db"))

    assert column in _columns(tmp_path / "old.db", "generations")


@pytest.mark.parametrize("column", ["level", "ref_prompt_id"])
def test_an_early_database_gains_every_folder_meta_column(tmp_path, column):
    Database(_database_as_first_written(tmp_path / "old.db"))

    assert column in _columns(tmp_path / "old.db", "folder_meta")


def test_the_generations_already_there_survive_the_migration(tmp_path):
    # The point of patching columns in rather than recreating the table: what the
    # user already made stays, and the new columns are writable on it.
    db = Database(_database_as_first_written(tmp_path / "old.db"))

    db.update_generation("old-001", duration_seconds=9.5)

    assert db.get_generation("old-001")["duration_seconds"] == 9.5


def test_mark_evolver_exported_persists_across_reopen(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.insert_generation(
        prompt_id="vid-001",
        workflow_name="wan22_i2v",
        workflow_version="v1",
        params_json="{}",
        workflow_json="{}",
    )
    # A never-sent video carries no export timestamp.
    assert db.get_generation("vid-001")["evolver_exported_at"] is None

    db.mark_evolver_exported("vid-001")

    # Reopening the file (a fresh app session) must still remember the send.
    reopened = Database(db_path)
    assert reopened.get_generation("vid-001")["evolver_exported_at"] is not None


def test_opening_db_without_evolver_column_migrates_it(tmp_path):
    db_path = tmp_path / "old.db"
    # Faithful pre-evolver schema: the table as it was before this column.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE generations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " prompt_id TEXT NOT NULL UNIQUE,"
        " source TEXT NOT NULL DEFAULT 'generated',"
        " workflow_name TEXT NOT NULL,"
        " workflow_version TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
        " params_json TEXT NOT NULL,"
        " workflow_json TEXT NOT NULL,"
        " output_files TEXT, thumbnail_path TEXT, error_message TEXT,"
        " duration_seconds REAL,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " completed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO generations"
        " (prompt_id, workflow_name, workflow_version, params_json, workflow_json)"
        " VALUES ('old-001', 'wan22_i2v', 'v1', '{}', '{}')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    assert db.get_generation("old-001")["evolver_exported_at"] is None
    db.mark_evolver_exported("old-001")
    assert db.get_generation("old-001")["evolver_exported_at"] is not None


def test_set_workflow_name_relabels_row(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="relabel-001",
        workflow_name="unknown",
        workflow_version="imported",
        params_json="{}",
        workflow_json="{}",
        source="imported",
    )
    db.set_workflow_name("relabel-001", "wan22_i2v")
    row = db.get_generation("relabel-001")
    assert row["workflow_name"] == "wan22_i2v"


def test_set_params_json_rewrites_row_params(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="fill-001",
        workflow_name="wan22_i2v",
        workflow_version="imported",
        params_json='{"seed": 1}',
        workflow_json="{}",
        source="imported",
    )
    db.set_params_json("fill-001", '{"seed": 1, "lora_high": "x.safetensors"}')
    row = db.get_generation("fill-001")
    assert json.loads(row["params_json"])["lora_high"] == "x.safetensors"


def test_star_generation_round_trips_across_reopen(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.insert_generation(
        prompt_id="s-001", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    )
    assert not db.get_generation("s-001")["starred"]  # unstarred by default

    db.set_generation_starred("s-001", True)
    # Reopening the file (a fresh app session) still remembers the star.
    assert Database(db_path).get_generation("s-001")["starred"]

    db.set_generation_starred("s-001", False)
    assert not db.get_generation("s-001")["starred"]


def test_opening_db_without_starred_column_migrates_it(tmp_path):
    db_path = tmp_path / "old.db"
    # Faithful pre-starred schema: the table as it was before this column.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE generations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " prompt_id TEXT NOT NULL UNIQUE,"
        " source TEXT NOT NULL DEFAULT 'generated',"
        " workflow_name TEXT NOT NULL,"
        " workflow_version TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
        " params_json TEXT NOT NULL,"
        " workflow_json TEXT NOT NULL,"
        " output_files TEXT, thumbnail_path TEXT, error_message TEXT,"
        " duration_seconds REAL,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " completed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO generations"
        " (prompt_id, workflow_name, workflow_version, params_json, workflow_json)"
        " VALUES ('old-001', 'sdxl_t2i', 'v002', '{}', '{}')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    assert not db.get_generation("old-001")["starred"]  # migrated in, defaulting off
    db.set_generation_starred("old-001", True)
    assert db.get_generation("old-001")["starred"]


def _add_completed(db, prompt_id, workflow_name, duration):
    db.insert_generation(
        prompt_id=prompt_id,
        workflow_name=workflow_name,
        workflow_version="v002",
        params_json="{}",
        workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed", duration_seconds=duration)


def test_recent_durations_filters_by_workflow_newest_first(tmp_path):
    db = Database(tmp_path / "test.db")
    _add_completed(db, "a", "sdxl_t2i", 10.0)
    _add_completed(db, "b", "wan22_i2v", 900.0)   # different workflow, excluded
    _add_completed(db, "c", "sdxl_t2i", 12.0)
    # A still-running sdxl row has no duration and must be excluded.
    db.insert_generation(
        prompt_id="d", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    )

    assert db.recent_durations("sdxl_t2i") == [12.0, 10.0]


def test_recent_durations_respects_limit(tmp_path):
    db = Database(tmp_path / "test.db")
    for i in range(5):
        _add_completed(db, f"r{i}", "sdxl_t2i", float(i))
    assert db.recent_durations("sdxl_t2i", limit=2) == [4.0, 3.0]


def test_completed_without_duration_selects_backfill_candidates(tmp_path):
    db = Database(tmp_path / "test.db")
    # Needs a duration: completed, has a completed_at, duration still NULL.
    db.insert_generation(prompt_id="needs", workflow_name="sdxl_t2i",
                         workflow_version="imported", params_json="{}",
                         workflow_json="{}", source="imported")
    db.update_generation("needs", status="completed", completed_at="2026-06-29T12:00:00+00:00")
    # Already timed — excluded.
    _add_completed(db, "timed", "sdxl_t2i", 5.0)
    # Still running — excluded.
    db.insert_generation(prompt_id="running", workflow_name="sdxl_t2i",
                         workflow_version="v002", params_json="{}", workflow_json="{}")

    rows = db.completed_without_duration()
    assert [r["prompt_id"] for r in rows] == ["needs"]
    assert rows[0]["completed_at"] == "2026-06-29T12:00:00+00:00"


def test_folder_meta_starts_empty(tmp_path):
    db = Database(tmp_path / "test.db")
    assert db.folder_meta_map() == {}


def test_rename_folder_round_trips(tmp_path):
    db = Database(tmp_path / "test.db")
    db.rename_folder("video/wan22_i2v", "Dance clips")
    assert db.folder_meta_map()["video/wan22_i2v"]["custom_name"] == "Dance clips"


def test_star_folder_round_trips_and_preserves_custom_name(tmp_path):
    db = Database(tmp_path / "test.db")
    db.rename_folder("image/sdxl_t2i", "Portraits")
    db.set_folder_starred("image/sdxl_t2i", True)

    meta = db.folder_meta_map()["image/sdxl_t2i"]
    assert meta["starred"] is True
    assert meta["custom_name"] == "Portraits"  # starring must not wipe the name

    db.set_folder_starred("image/sdxl_t2i", False)
    assert db.folder_meta_map()["image/sdxl_t2i"]["starred"] is False


def test_folder_meta_full_reports_identity_columns(tmp_path):
    db = Database(tmp_path / "test.db")
    db.upsert_folder_meta("image/sdxl_t2i/abc123", custom_name="Cats", starred=True,
                          level="settings", ref_prompt_id="p1")
    assert db.folder_meta_full() == [{
        "folder_key": "image/sdxl_t2i/abc123", "custom_name": "Cats",
        "starred": True, "level": "settings", "ref_prompt_id": "p1",
    }]


def test_a_star_set_through_the_plain_api_has_null_identity(tmp_path):
    # The view stars by key alone; a bookmark's identity (tier + a member row)
    # stays NULL until the reconcile backfills it, so folder_meta_full surfaces that.
    db = Database(tmp_path / "test.db")
    db.set_folder_starred("image/sdxl_t2i", True)
    (row,) = db.folder_meta_full()
    assert row["starred"] is True
    assert row["level"] is None and row["ref_prompt_id"] is None


def test_upsert_folder_meta_overwrites_every_field(tmp_path):
    db = Database(tmp_path / "test.db")
    db.set_folder_starred("k", True)
    db.upsert_folder_meta("k", custom_name="N", starred=False,
                          level="model", ref_prompt_id="p2")
    (row,) = db.folder_meta_full()
    assert row["custom_name"] == "N" and row["starred"] is False
    assert row["level"] == "model" and row["ref_prompt_id"] == "p2"


def test_delete_folder_meta_removes_the_row(tmp_path):
    db = Database(tmp_path / "test.db")
    db.set_folder_starred("k", True)
    db.delete_folder_meta("k")
    assert db.folder_meta_full() == []


def test_list_generations_ordered_newest_first(tmp_path):
    db = Database(tmp_path / "test.db")
    for i in range(3):
        db.insert_generation(
            prompt_id=f"list-{i:03d}",
            workflow_name="sdxl_t2i",
            workflow_version="v002",
            params_json="{}",
            workflow_json="{}",
        )
    rows = db.list_generations()
    assert len(rows) == 3
    assert rows[0]["prompt_id"] == "list-002"
    assert rows[2]["prompt_id"] == "list-000"


def test_opening_db_without_experiment_verdict_column_migrates_it(tmp_path):
    db_path = tmp_path / "old.db"
    # Faithful pre-experiment schema: the table as it was before this column.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE generations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " prompt_id TEXT NOT NULL UNIQUE,"
        " source TEXT NOT NULL DEFAULT 'generated',"
        " workflow_name TEXT NOT NULL,"
        " workflow_version TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
        " params_json TEXT NOT NULL,"
        " workflow_json TEXT NOT NULL,"
        " output_files TEXT, thumbnail_path TEXT, error_message TEXT,"
        " starred INTEGER NOT NULL DEFAULT 0,"
        " progress_json TEXT,"
        " duration_seconds REAL,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " completed_at TEXT, evolver_exported_at TEXT)"
    )
    conn.execute(
        "INSERT INTO generations"
        " (prompt_id, workflow_name, workflow_version, params_json, workflow_json)"
        " VALUES ('old-001', 'sdxl_t2i', 'v002', '{}', '{}')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    db.set_experiment_verdict("old-001", "up")
    assert db.get_generation("old-001")["experiment_verdict"] == "up"


def test_experiment_verdict_round_trips(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="exp-001", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}", source="experiment",
    )
    assert db.get_generation("exp-001")["experiment_verdict"] is None
    db.set_experiment_verdict("exp-001", "up")
    assert db.get_generation("exp-001")["experiment_verdict"] == "up"
    db.set_experiment_verdict("exp-001", "down")
    assert db.get_generation("exp-001")["experiment_verdict"] == "down"


def test_delete_generation_removes_row(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="del-001", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    )
    db.insert_generation(
        prompt_id="del-002", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    )
    db.delete_generation("del-001")
    assert db.get_generation("del-001") is None
    assert db.get_generation("del-002") is not None


def test_restore_generation_brings_back_a_deleted_row_intact(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="r-001", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", negative_prompt="ugly", seed=7,
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    )
    db.update_generation(
        "r-001", status="completed",
        output_files=json.dumps([{"filename": "out.png", "subfolder": ""}]),
        thumbnail_path="thumbs/out.jpg", duration_seconds=12.5,
    )
    original = db.get_generation("r-001")
    db.delete_generation("r-001")
    assert db.get_generation("r-001") is None

    db.restore_generation(original)

    restored = db.get_generation("r-001")
    # Every column survives the round-trip, id and created_at included, so the
    # restored row sorts back into its original gallery position.
    assert restored == original


def test_restore_generation_preserves_newest_first_order(tmp_path):
    db = Database(tmp_path / "test.db")
    for i in range(3):
        db.insert_generation(
            prompt_id=f"o-{i}", workflow_name="sdxl_t2i", workflow_version="v002",
            params_json="{}", workflow_json="{}",
        )
    middle = db.get_generation("o-1")
    db.delete_generation("o-1")
    db.restore_generation(middle)

    # Restored by its original id, the row lands back in the middle, not on top.
    assert [r["prompt_id"] for r in db.list_generations()] == ["o-2", "o-1", "o-0"]


# --- the recovery bin (held deletions) -------------------------------------


def test_a_recorded_deletion_comes_back_as_data(tmp_path):
    db = Database(tmp_path / "test.db")
    row = {"prompt_id": "d-1", "seed": 7}
    batch = {"moves": [["out/a.png", "trash/abc/0_a.png"]], "subdir": "trash/abc"}

    db.record_deletion("d-1", row, batch)

    held = db.get_deletion("d-1")
    assert held["prompt_id"] == "d-1"
    assert held["row"] == row       # JSON columns arrive parsed, not as strings
    assert held["batch"] == batch
    assert held["deleted_at"]       # stamped, so the sweep can age it out


def test_held_deletions_list_newest_first(tmp_path):
    db = Database(tmp_path / "test.db")
    for prompt_id in ("d-1", "d-2", "d-3"):
        db.record_deletion(prompt_id, {"prompt_id": prompt_id}, {})

    # Same-second stamps tie, so the insertion order is what breaks it.
    assert [r["prompt_id"] for r in db.list_deletions()] == ["d-3", "d-2", "d-1"]


def test_re_deleting_an_item_restarts_its_window(tmp_path):
    # Deleted, restored, deleted again: one record, held from the latest delete.
    db = Database(tmp_path / "test.db")
    db.record_deletion("d-1", {"prompt_id": "d-1"}, {"moves": [], "subdir": "first"})
    db.record_deletion("d-1", {"prompt_id": "d-1"}, {"moves": [], "subdir": "second"})

    (held,) = db.list_deletions()
    assert held["batch"]["subdir"] == "second"


def test_forgetting_a_deletion_drops_it_from_the_bin(tmp_path):
    db = Database(tmp_path / "test.db")
    db.record_deletion("d-1", {"prompt_id": "d-1"}, {})

    db.forget_deletion("d-1")

    assert db.get_deletion("d-1") is None
    assert db.list_deletions() == []


def test_an_unheld_deletion_is_simply_absent(tmp_path):
    db = Database(tmp_path / "test.db")
    assert db.get_deletion("never") is None
    db.forget_deletion("never")  # must not raise


# --- spoken requests (what the Requests shelf lists) -------------------------


def _record(db, prompt_id, source="src-1", heard="Request, no hat, over."):
    db.record_request(
        prompt_id=prompt_id, source_prompt_id=source, heard=heard,
        term="hat", polarity="remove", action="dropped",
        old_positive="a woman, a hat", old_negative="blurry",
        new_positive="a woman", new_negative="blurry",
    )


def test_a_recorded_request_comes_back_whole(tmp_path):
    db = Database(tmp_path / "test.db")
    _record(db, "gen-1")

    record = db.get_request("gen-1")

    assert record["source_prompt_id"] == "src-1"
    assert record["heard"] == "Request, no hat, over."
    assert record["term"] == "hat"
    assert record["old_positive"] == "a woman, a hat"
    assert record["new_positive"] == "a woman"


def test_requests_list_newest_first(tmp_path):
    db = Database(tmp_path / "test.db")
    _record(db, "gen-1")
    _record(db, "gen-2")

    assert [r["prompt_id"] for r in db.list_requests()] == ["gen-2", "gen-1"]


def test_a_generation_nothing_asked_for_has_no_request(tmp_path):
    db = Database(tmp_path / "test.db")
    assert db.get_request("gen-unasked") is None


def test_a_request_outlives_the_generation_it_queued(tmp_path):
    # A delete here is undoable, so the record has to be waiting if the item
    # comes back; the shelf skips what it can't resolve instead.
    db = Database(tmp_path / "test.db")
    _record(db, "gen-1")

    db.delete_generation("gen-1")

    assert db.get_request("gen-1") is not None
def test_the_genau_marks_are_independent_of_evolvers(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.insert_generation(
        prompt_id="clip-001",
        workflow_name="wan22_flf2v_loop",
        workflow_version="v006",
        params_json="{}",
        workflow_json="{}",
    )
    row = db.get_generation("clip-001")
    assert row["genau_requested_at"] is None and row["genau_exported_at"] is None

    db.mark_genau_requested("clip-001")   # a spoken "genau it" started this run
    db.mark_genau_exported("clip-001")    # and it was handed on once it existed

    reopened = Database(db_path).get_generation("clip-001")
    assert reopened["genau_requested_at"] is not None
    assert reopened["genau_exported_at"] is not None
    # The two lanes are separate errands: sending down one says nothing about the other.
    assert reopened["evolver_exported_at"] is None


def test_opening_db_without_the_genau_columns_migrates_them(tmp_path):
    db_path = tmp_path / "old.db"
    # The schema as it stood when Evolver was the only place a video could be sent.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE generations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " prompt_id TEXT NOT NULL UNIQUE,"
        " source TEXT NOT NULL DEFAULT 'generated',"
        " workflow_name TEXT NOT NULL,"
        " workflow_version TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
        " params_json TEXT NOT NULL,"
        " workflow_json TEXT NOT NULL,"
        " output_files TEXT, thumbnail_path TEXT, error_message TEXT,"
        " duration_seconds REAL,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " completed_at TEXT, evolver_exported_at TEXT)"
    )
    conn.execute(
        "INSERT INTO generations"
        " (prompt_id, workflow_name, workflow_version, params_json, workflow_json)"
        " VALUES ('old-001', 'wan22_flf2v_loop', 'v006', '{}', '{}')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    assert db.get_generation("old-001")["genau_exported_at"] is None
    db.mark_genau_requested("old-001")
    db.mark_genau_exported("old-001")
    row = db.get_generation("old-001")
    assert row["genau_requested_at"] is not None and row["genau_exported_at"] is not None
