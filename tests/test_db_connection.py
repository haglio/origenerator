from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from origenerator.db_connection import SqliteFile


@pytest.fixture
def file(tmp_path) -> SqliteFile:
    database = SqliteFile(tmp_path / "example.db")
    with database.connect() as conn:
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    return database


def test_what_a_block_wrote_is_there_for_the_next_one(file):
    with file.connect() as conn:
        conn.execute("INSERT INTO notes (body) VALUES (?)", ("scene one",))

    with file.connect() as conn:
        assert [r["body"] for r in conn.execute("SELECT body FROM notes")] == ["scene one"]


def test_the_log_names_the_rows_this_file_changed_since_it_was_last_asked(file):
    log = file.log_own_changes("notes", "body")
    log.changed_since_last_asked()
    with file.connect() as conn:
        conn.execute("INSERT INTO notes (body) VALUES ('scene one'), ('scene two')")
        conn.execute("UPDATE notes SET body = 'scene three' WHERE body = 'scene two'")

    assert log.changed_since_last_asked() == {"scene one", "scene two", "scene three"}
    assert log.changed_since_last_asked() == set()


def test_the_log_cannot_say_what_another_connection_changed(file):
    log = file.log_own_changes("notes", "body")
    log.changed_since_last_asked()
    with closing(sqlite3.connect(file.path)) as other, other:
        other.execute("INSERT INTO notes (body) VALUES ('scene one')")

    assert log.changed_since_last_asked() is None
    assert log.changed_since_last_asked() == set()


def test_the_log_cannot_say_anything_the_first_time_it_is_asked(file):
    assert file.log_own_changes("notes", "body").changed_since_last_asked() is None


def _write_half_a_batch(file):
    with file.connect() as conn:
        conn.execute("INSERT INTO notes (body) VALUES (?)", ("scene two",))
        raise ValueError("half a batch")


def test_a_block_that_raises_writes_nothing(file):
    with pytest.raises(ValueError, match="half a batch"):
        _write_half_a_batch(file)

    with file.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_rows_come_back_by_column_name(file):
    with file.connect() as conn:
        conn.execute("INSERT INTO notes (body) VALUES (?)", ("scene three",))
        row = conn.execute("SELECT id, body FROM notes").fetchone()

    assert row["body"] == "scene three"


def test_the_version_moves_with_every_commit_though_the_watcher_never_writes(file):
    before = file.version()
    with file.connect() as conn:
        conn.execute("INSERT INTO notes (body) VALUES ('example')")
    assert file.version() != before
