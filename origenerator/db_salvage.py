from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from origenerator.db_schema import RENAMED_TABLES

logger = logging.getLogger(__name__)


def salvage_if_malformed(path: Path, schema: str) -> None:
    if not path.exists() or _reads_clean(path):
        return
    rebuilt = path.with_name(path.name + ".rebuilt")
    rebuilt.unlink(missing_ok=True)
    read_only = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(read_only, uri=True)) as damaged, \
            closing(sqlite3.connect(rebuilt)) as fresh:
        _match_journal_mode(fresh, damaged)
        fresh.executescript(schema)
        kept = {table: _copy_table(damaged, fresh, table) for table in _tables(fresh)}
        fresh.commit()
    damaged_copy = path.with_name(path.name + ".corrupt")
    _move_aside(path, damaged_copy)
    rebuilt.replace(path)
    logger.warning(
        "Database was malformed: salvaged %s into a fresh file; the damaged one is kept at %s",
        ", ".join(f"{n} {table}" for table, n in kept.items()), damaged_copy,
    )


def _move_aside(path: Path, target: Path) -> None:
    # SQLite finds a write-ahead log by file name, so a left-over one would be replayed into the rebuilt database.
    for suffix in ("", "-wal", "-shm"):
        source = path.with_name(path.name + suffix)
        destination = target.with_name(target.name + suffix)
        destination.unlink(missing_ok=True)
        if source.exists():
            source.replace(destination)


def _reads_clean(path: Path) -> bool:
    with closing(sqlite3.connect(path)) as conn:
        try:
            return conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        except sqlite3.DatabaseError:
            return False


def _match_journal_mode(fresh, damaged) -> None:
    mode = damaged.execute("PRAGMA journal_mode").fetchone()[0]
    fresh.execute(f"PRAGMA journal_mode = {mode}")


def _tables(conn) -> list[str]:
    return [
        name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]


def _copy_table(damaged, fresh, table: str) -> int:
    # SQLite: a single scan stops at the first damaged page, so it reads one rowid at a time.
    source = _source_of(damaged, table)
    columns = [c for c in _columns(damaged, source) if c in _columns(fresh, table)]
    select = f'SELECT {", ".join(columns)} FROM "{source}" WHERE rowid = ?'
    insert = (f'INSERT INTO "{table}" ({", ".join(columns)}) '
              f'VALUES ({", ".join("?" for _ in columns)})')
    kept = 0
    for rowid in range(1, _highest_rowid(damaged, source) + 1):
        try:
            row = damaged.execute(select, (rowid,)).fetchone()
            if row is None:
                continue
            fresh.execute(insert, row)
        except sqlite3.DatabaseError:
            continue
        kept += 1
    return kept


def _source_of(damaged, table: str) -> str:
    if _columns(damaged, table):
        return table
    return next((old for old, new in RENAMED_TABLES.items()
                 if new == table and _columns(damaged, old)), table)


def _columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _highest_rowid(conn, table: str) -> int:
    # SQLite: max(rowid) walks to the rightmost leaf, where damage is likeliest; sqlite_sequence keeps the same mark apart.
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
