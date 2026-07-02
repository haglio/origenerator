import json
import sqlite3

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


def test_opening_db_without_duration_column_migrates_it(tmp_path):
    db_path = tmp_path / "old.db"
    # Faithful pre-duration_seconds schema: everything the table has had since
    # the start, minus the column this migration adds.
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
        "INSERT INTO generations"
        " (prompt_id, workflow_name, workflow_version, params_json, workflow_json)"
        " VALUES ('old-001', 'sdxl_t2i', 'v002', '{}', '{}')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
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
