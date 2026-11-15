from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from origenerator.db import Database
from origenerator.db_generations import GenerationSource
from origenerator.db_schema import STORED_NAMES

_DEFAULTS = {"workflow_name": "sdxl_t2i", "workflow_version": "v1", "params_json": "{}",
             "workflow_json": "{}", "source": GenerationSource.GENERATED}


def database_in(folder: Path, rows: Iterable[dict] = (), *,
                kind: type[Database] = Database) -> Database:
    db = kind(_unused_folder(Path(folder) / "database") / "origenerator.db")
    put_rows(db, rows)
    return db


def _unused_folder(first: Path) -> Path:
    folder, n = first, 1
    while folder.exists():
        n += 1
        folder = first.with_name(f"{first.name} {n}")
    return folder


def put_rows(db: Database, rows: Iterable[dict]) -> None:
    rows = [{STORED_NAMES.get(name, name): value for name, value in {**_DEFAULTS, **row}.items()}
            for row in rows]
    if not rows:
        return
    with sqlite3.connect(db.path) as conn:
        for row in rows:
            conn.execute(f"INSERT INTO generations ({', '.join(row)}) "
                         f"VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    conn.close()
