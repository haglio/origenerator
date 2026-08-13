"""Rebuilding a database file that was damaged from outside SQLite.

SQLite keeps its own writes consistent, but the file is still just a file: a
stray write from elsewhere in the process lands in it like any other, and from
then on every read that crosses the damaged page raises ``database disk image is
malformed``. That is fatal to the app -- the gallery reads the whole table to
build itself, so the window never appears -- even when only one page in
thousands is unreachable.

So on open, a damaged file is rebuilt: every row still reachable is copied into
a fresh database, the damaged file is kept beside it, and the app comes up
missing at most the rows that sat on the damaged pages.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)


def salvage_if_malformed(path: Path, schema: str) -> None:
    """Rebuild ``path`` under ``schema`` if its file no longer reads cleanly.

    A no-op for a healthy (or not-yet-created) database, which is every start
    but the one after damage.
    """
    if not path.exists() or _reads_clean(path):
        return
    rebuilt = path.with_name(path.name + ".rebuilt")
    rebuilt.unlink(missing_ok=True)
    read_only = f"{path.resolve().as_uri()}?mode=ro"  # never write to the damaged file
    with closing(sqlite3.connect(read_only, uri=True)) as damaged, \
            closing(sqlite3.connect(rebuilt)) as fresh:
        _match_journal_mode(fresh, damaged)
        fresh.executescript(schema)
        kept = {table: _copy_table(damaged, fresh, table) for table in _tables(fresh)}
        fresh.commit()
    damaged_copy = path.with_name(path.name + ".corrupt")  # a salvage destroys nothing
    _move_aside(path, damaged_copy)
    rebuilt.replace(path)
    logger.warning(
        "Database was malformed: salvaged %s into a fresh file; the damaged one is kept at %s",
        ", ".join(f"{n} {table}" for table, n in kept.items()), damaged_copy,
    )


def _move_aside(path: Path, target: Path) -> None:
    """Move a database and its journal files out of the way as one thing.

    A write-ahead log names no database of its own -- SQLite finds it by the
    file name beside it -- so one left behind would be replayed into whatever
    inherits that name, which here is the freshly rebuilt database.
    """
    for suffix in ("", "-wal", "-shm"):
        source = path.with_name(path.name + suffix)
        destination = target.with_name(target.name + suffix)
        destination.unlink(missing_ok=True)
        if source.exists():
            source.replace(destination)


def _reads_clean(path: Path) -> bool:
    """Whether SQLite can still walk the whole file."""
    with closing(sqlite3.connect(path)) as conn:
        try:
            return conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        except sqlite3.DatabaseError:
            return False  # too damaged to even check


def _match_journal_mode(fresh, damaged) -> None:
    """Give the rebuilt file the journaling the damaged one was running.

    The mode lives in the file, not in the code that opens it, so a rebuild that
    forgets it silently swaps the database's concurrency out from under the app.
    """
    mode = damaged.execute("PRAGMA journal_mode").fetchone()[0]
    fresh.execute(f"PRAGMA journal_mode = {mode}")


def _tables(conn) -> list[str]:
    return [
        name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]


def _copy_table(damaged, fresh, table: str) -> int:
    """Copy every row of ``table`` the damaged file will still hand over.

    One rowid at a time: a single scan would stop dead at the first damaged
    page, where asking row by row loses only the rows actually on it. A row is
    dropped both when the damaged file cannot produce it and when the fresh one
    refuses it -- what a damaged file hands back is not to be trusted, and one
    unusable row must not cost the thousands around it.
    """
    columns = [c for c in _columns(damaged, table) if c in _columns(fresh, table)]
    select = f'SELECT {", ".join(columns)} FROM "{table}" WHERE rowid = ?'
    insert = (f'INSERT INTO "{table}" ({", ".join(columns)}) '
              f'VALUES ({", ".join("?" for _ in columns)})')
    kept = 0
    for rowid in range(1, _highest_rowid(damaged, table) + 1):
        try:
            row = damaged.execute(select, (rowid,)).fetchone()
            if row is None:
                continue
            fresh.execute(insert, row)
        except sqlite3.DatabaseError:
            continue
        kept += 1
    return kept


def _columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _highest_rowid(conn, table: str) -> int:
    """How far to count, from whichever record of it survived.

    ``max(rowid)`` walks the table to its rightmost leaf -- where the newest
    rows live, and so exactly where damage is likeliest -- while
    ``sqlite_sequence`` holds the same high-water mark in a one-row table of its
    own that such damage leaves alone.
    """
    for sql, args in (
        (f'SELECT max(rowid) FROM "{table}"', ()),
        ("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)),
    ):
        try:
            row = conn.execute(sql, args).fetchone()
        except sqlite3.DatabaseError:
            continue
        if row is not None and row[0] is not None:
            return row[0]
    return 0
