from __future__ import annotations

import shutil
import sqlite3

from origenerator.db import Database, NewGeneration

PAGE = 4096
FILLER = "x" * 2500


def _fill(path, count):
    db = Database(path)
    for i in range(count):
        db.insert_generation(NewGeneration(
            prompt_id=f"job-{i}",
            workflow_name="sdxl_t2i",
            workflow_version="v002",
            positive_prompt=f"marker-{i}-{FILLER}",
            params_json="{}",
            workflow_json="{}",
        ))


def _journal_mode(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def _set_journal_mode(path, mode):
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA journal_mode = {mode}")
    finally:
        conn.close()


def _leave_a_hot_journal(path, rows):
    staged = path.with_name("staged.db")
    _fill(staged, rows)
    _set_journal_mode(staged, "wal")
    holding = sqlite3.connect(staged)
    holding.execute(
        "INSERT INTO generations (prompt_id, workflow_name, workflow_version,"
        " params_json, workflow_json) VALUES ('job-in-the-log', 'sdxl_t2i', 'v002', '{}', '{}')"
    )
    holding.commit()
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(f"{staged}{suffix}", f"{path}{suffix}")
    holding.close()


def _stray_write_over(path, marker):
    data = bytearray(path.read_bytes())
    page = data.index(marker.encode()) // PAGE
    data[page * PAGE:page * PAGE + 10] = b"Input #0, "
    path.write_bytes(bytes(data))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]
    except sqlite3.DatabaseError:
        pass
    finally:
        conn.close()


def test_a_malformed_database_opens_with_every_row_still_readable(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 12)
    _stray_write_over(path, "marker-5-")

    rows = Database(path).list_generations()

    assert [r["prompt_id"] for r in rows] == [
        f"job-{i}" for i in reversed(range(12)) if i != 5
    ]


def test_the_damaged_file_is_kept_beside_the_rebuilt_one(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 12)
    _stray_write_over(path, "marker-5-")
    damaged = path.read_bytes()

    Database(path)

    assert (tmp_path / "origenerator.db.corrupt").read_bytes() == damaged


def test_damage_to_the_newest_rows_does_not_cost_the_older_ones(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 12)
    _stray_write_over(path, "marker-11-")

    rows = Database(path).list_generations()

    assert [r["prompt_id"] for r in rows] == [f"job-{i}" for i in reversed(range(11))]


def test_the_rebuilt_database_keeps_the_journal_mode_it_replaced(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 6)
    _set_journal_mode(path, "wal")
    _stray_write_over(path, "marker-3-")

    Database(path)

    assert _journal_mode(path) == "wal"


def test_the_damaged_files_write_ahead_log_goes_aside_with_it(tmp_path):
    path = tmp_path / "origenerator.db"
    _leave_a_hot_journal(path, rows=6)
    _stray_write_over(path, "marker-3-")

    Database(path)

    assert (tmp_path / "origenerator.db.corrupt-wal").exists()
    assert not (tmp_path / "origenerator.db-wal").exists()


def test_a_healthy_database_is_opened_untouched(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 3)

    rows = Database(path).list_generations()

    assert [r["prompt_id"] for r in rows] == ["job-2", "job-1", "job-0"]
    assert [p.name for p in tmp_path.iterdir()] == ["origenerator.db"]


def test_a_database_damaged_before_the_table_rename_keeps_its_folders(tmp_path):
    path = tmp_path / "origenerator.db"
    _fill(path, 4)
    db = Database(path)
    folder_id = db.create_custom_collection("Mine")
    db.add_folders_to_custom_collection(folder_id, [("key-a", "L1", "job-0"),
                                                ("key-b", "L1", "job-1")])
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE custom_folder_items RENAME TO custom_collection_members")
        conn.commit()
    finally:
        conn.close()
    _stray_write_over(path, "marker-2-")

    folders = Database(path).list_custom_collections()

    assert [f["folders"] for f in folders] == [["key-a", "key-b"]]
