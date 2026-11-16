from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from origenerator.db import Database
from origenerator.db_generations import GenerationSource
from origenerator.db_schema import GENERATION_COLUMNS, STORED_NAMES

_DEFAULTS = {"workflow_name": "sdxl_t2i", "workflow_version": "v1", "params_json": "{}",
             "workflow_json": "{}", "source": GenerationSource.GENERATED}

DATABASES = Path("set for each test by conftest")


def database_in(folder: Path, rows: Iterable[dict] = (), *,
                kind: type[Database] = Database) -> Database:
    db = kind(_unused_folder(Path(folder) / "database") / "origenerator.db")
    put_rows(db, rows)
    return db


def database_of(newest_first: Iterable[dict] = (), *,
                kind: type[Database] = Database) -> Database:
    return database_in(DATABASES, reversed(list(newest_first)), kind=kind)


def _unused_folder(first: Path) -> Path:
    folder, n = first, 1
    while folder.exists():
        n += 1
        folder = first.with_name(f"{first.name} {n}")
    return folder


def put_rows(db: Database, rows: Iterable[dict]) -> None:
    rows = [{**_DEFAULTS, **row} for row in rows]
    for row in rows:
        if unknown := set(row) - set(GENERATION_COLUMNS) - set(STORED_NAMES):
            raise KeyError(f"{row['prompt_id']} names no column the gallery keeps: {sorted(unknown)}")
    db.insert_rows(rows)


def kept_on_disk(db: Database, row: dict, path: Path) -> dict:
    files = json.loads(row.get("output_files") or "[]") or [{"filename": path.name}]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _write_a_stand_in(path)
    db.update_generation(row["prompt_id"], output_files=json.dumps(
        [{**files[0], "path": str(path)}, *files[1:]]))
    return db.get_generation(row["prompt_id"])


def _write_a_stand_in(path: Path) -> None:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        Image.new("RGB", (4, 4), "gray").save(path)
    else:
        path.write_bytes(b"kept")
