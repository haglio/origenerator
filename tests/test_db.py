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
