"""The one way this package opens its database file.

Every query in every store goes through :class:`SqliteFile.connect`, so the two
things it promises — commit on the way out, close whatever happens — are worth
one test each rather than being re-asserted in six store modules.

Closing is the half with a bug behind it: the plain ``with sqlite3.connect(...)``
this replaced commits and then leaves the connection to the garbage collector,
which on Windows keeps the file open long enough for the next rename or replace
of it to be refused (see origenerator.db_salvage).

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import sqlite3

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


def test_the_connection_is_closed_on_the_way_out(file):
    with file.connect() as conn:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_the_connection_is_closed_even_when_the_block_raises(file):
    with pytest.raises(ValueError):
        with file.connect() as conn:
            raise ValueError("something in the middle of a write")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_a_block_that_raises_writes_nothing(file):
    with pytest.raises(ValueError):
        with file.connect() as conn:
            conn.execute("INSERT INTO notes (body) VALUES (?)", ("scene two",))
            raise ValueError("half a batch")

    with file.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_rows_come_back_by_column_name(file):
    """Every store reads its rows as ``row["column"]``; a default connection
    hands back plain tuples and every one of them would be a TypeError."""
    with file.connect() as conn:
        conn.execute("INSERT INTO notes (body) VALUES (?)", ("scene three",))
        row = conn.execute("SELECT id, body FROM notes").fetchone()

    assert row["body"] == "scene three"
