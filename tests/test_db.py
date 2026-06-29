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
