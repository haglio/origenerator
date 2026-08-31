"""The bytes on disk, written down — because another app reads them.

`origenerator/db.py` is about to be split along table ownership, and the one
thing that split must not move is the file it opens. Evolver mounts this
database read-only and selects seven columns off `generations` by name
(`evolver/tasks/origenerator_metadata.py`, its `_SELECT`), so a rename there is
a broken sibling with no test of ours to say so; and every user's existing
database is migrated in place, so a column that stops being created is data that
stops being readable.

So the whole schema is a snapshot here: every table, every column with its type,
its NOT NULL, its default and its place in the primary key, and every index. A
column ADDED to the schema fails this test, which is the point — adding one is a
deliberate act that should have to be written down twice, once in the DDL and
once here. Nothing in the split below may touch it.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import sqlite3
from pathlib import Path

import pytest

from origenerator.db import _GENERATION_COLUMNS, Database

# (name, type, not_null, default, primary_key_position) per column, in
# declaration order — exactly what `PRAGMA table_info` reports.
SCHEMA = {
    "branch_curation": (
        ("branch", "TEXT", 0, None, 1),
        ("state_json", "TEXT", 1, None, 0),
        ("adopted_at", "TEXT", 1, "datetime('now')", 0),
    ),
    "custom_folder_members": (
        ("folder_id", "INTEGER", 1, None, 1),
        ("folder_key", "TEXT", 1, None, 2),
        ("level", "TEXT", 0, None, 0),
        ("ref_prompt_id", "TEXT", 0, None, 0),
        ("position", "INTEGER", 1, "0", 0),
    ),
    "custom_folders": (
        ("id", "INTEGER", 0, None, 1),
        ("name", "TEXT", 1, None, 0),
        ("created_at", "TEXT", 1, "datetime('now')", 0),
    ),
    "deletions": (
        ("prompt_id", "TEXT", 0, None, 1),
        ("row_json", "TEXT", 1, None, 0),
        ("batch_json", "TEXT", 1, None, 0),
        ("deleted_at", "TEXT", 1, "datetime('now')", 0),
    ),
    "folder_meta": (
        ("folder_key", "TEXT", 0, None, 1),
        ("custom_name", "TEXT", 0, None, 0),
        ("starred", "INTEGER", 1, "0", 0),
        ("level", "TEXT", 0, None, 0),
        ("ref_prompt_id", "TEXT", 0, None, 0),
    ),
    "generations": (
        ("id", "INTEGER", 0, None, 1),
        ("prompt_id", "TEXT", 1, None, 0),
        ("source", "TEXT", 1, "'generated'", 0),
        ("workflow_name", "TEXT", 1, None, 0),
        ("workflow_version", "TEXT", 1, None, 0),
        ("status", "TEXT", 1, "'pending'", 0),
        ("positive_prompt", "TEXT", 0, None, 0),
        ("negative_prompt", "TEXT", 0, None, 0),
        ("seed", "INTEGER", 0, None, 0),
        ("params_json", "TEXT", 1, None, 0),
        ("workflow_json", "TEXT", 1, None, 0),
        ("output_files", "TEXT", 0, None, 0),
        ("original_files", "TEXT", 0, None, 0),
        ("enhance_history", "TEXT", 0, None, 0),
        ("thumbnail_path", "TEXT", 0, None, 0),
        ("error_message", "TEXT", 0, None, 0),
        ("starred", "INTEGER", 1, "0", 0),
        ("progress_json", "TEXT", 0, None, 0),
        ("experiment_verdict", "TEXT", 0, None, 0),
        ("duration_seconds", "REAL", 0, None, 0),
        ("created_at", "TEXT", 1, "datetime('now')", 0),
        ("completed_at", "TEXT", 0, None, 0),
        ("evolver_exported_at", "TEXT", 0, None, 0),
        ("genau_exported_at", "TEXT", 0, None, 0),
        ("genau_requested_at", "TEXT", 0, None, 0),
        ("recipe_category", "TEXT", 0, None, 0),
        ("recipe_video_id", "TEXT", 0, None, 0),
    ),
    "requests": (
        ("prompt_id", "TEXT", 0, None, 1),
        ("source_prompt_id", "TEXT", 1, None, 0),
        ("heard", "TEXT", 1, None, 0),
        ("term", "TEXT", 0, None, 0),
        ("polarity", "TEXT", 0, None, 0),
        ("action", "TEXT", 0, None, 0),
        ("old_positive", "TEXT", 0, None, 0),
        ("old_negative", "TEXT", 0, None, 0),
        ("new_positive", "TEXT", 0, None, 0),
        ("new_negative", "TEXT", 0, None, 0),
        ("created_at", "TEXT", 1, "datetime('now')", 0),
    ),
}

# The indexes db.py declares by hand. sqlite's own `sqlite_autoindex_*` are not
# listed: they are a consequence of the primary keys above, so pinning them here
# would be pinning the same fact twice.
DECLARED_INDEXES = (
    "idx_generations_created",
    "idx_generations_status",
    "idx_generations_workflow",
)

# Evolver opens this database read-only and selects these seven off
# `generations` — see `evolver/tasks/origenerator_metadata.py`, whose `_SELECT`
# is reproduced in the test below. Renaming one is a broken sibling.
EVOLVER_COLUMNS = (
    "prompt_id", "positive_prompt", "negative_prompt", "seed",
    "params_json", "output_files", "created_at",
)


@pytest.fixture
def opened(tmp_path) -> sqlite3.Connection:
    """A freshly-created database, opened raw so the schema can be read off it."""
    path = tmp_path / "origenerator.db"
    Database(path)
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> tuple:
    return tuple(
        (row[1], row[2], row[3], row[4], row[5])
        for row in conn.execute(f"PRAGMA table_info({table})")
    )


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")
        if not row[0].startswith("sqlite_")
    }


def test_the_database_holds_exactly_these_tables(opened):
    assert _tables(opened) == set(SCHEMA)


@pytest.mark.parametrize("table", sorted(SCHEMA))
def test_a_tables_columns_are_what_they_have_always_been(opened, table):
    assert _columns(opened, table) == SCHEMA[table]


def test_the_declared_indexes_are_all_still_declared(opened):
    named = {
        row[0] for row in opened.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")
        if not row[0].startswith("sqlite_autoindex_")
    }

    assert named == set(DECLARED_INDEXES)


def test_evolvers_own_select_still_runs_against_this_database(opened):
    """Not the column names re-typed here, but the statement evolver issues,
    copied from `evolver/tasks/origenerator_metadata.py:_SELECT`. A rename on
    this side makes it an OperationalError rather than a silent miss."""
    evolver_select = (
        "SELECT prompt_id, positive_prompt, negative_prompt, seed, "
        "params_json, output_files, created_at FROM generations"
    )

    assert opened.execute(evolver_select).fetchall() == []


def test_the_seven_columns_evolver_pins_are_in_the_snapshot():
    """The control on the test above: it would pass just as happily against a
    statement nobody issues, so the names are checked against the schema too."""
    declared = {column for column, *_ in SCHEMA["generations"]}

    assert set(EVOLVER_COLUMNS) <= declared


def test_a_read_only_open_of_the_file_sees_the_whole_generations_table(tmp_path):
    """The way evolver opens it: `file:...?mode=ro`, on a database this app
    made and never blessed for another reader."""
    path = tmp_path / "origenerator.db"
    Database(path)

    uri = f"file:{Path(path).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        found = {row[1] for row in conn.execute("PRAGMA table_info(generations)")}

    assert found == {column for column, *_ in SCHEMA["generations"]}


def test_the_replayed_column_list_is_the_tables_own_order(opened):
    """`restore_generation` re-inserts a captured row by replaying
    `_GENERATION_COLUMNS` positionally, so a column added to the DDL and
    forgotten there is silently dropped from every undone delete."""
    assert _GENERATION_COLUMNS == tuple(
        column for column, *_ in SCHEMA["generations"])
