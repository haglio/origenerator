from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from origenerator.db import Database
from origenerator.db_generations import GenerationSource
from origenerator.db_schema import GENERATION_COLUMNS, STORED_NAMES

_DEFAULTS = {"workflow_name": "sdxl_t2i", "workflow_version": "v1", "params_json": "{}",
             "workflow_json": "{}", "source": GenerationSource.GENERATED}

THIS_TESTS_FOLDER = Path("set for each test by conftest")
ROWS_KEPT_ON_DISK = False


def database_in(folder: Path, rows: Iterable[dict] = (), *,
                kind: type[Database] = Database) -> Database:
    db = kind(_unused_folder(Path(folder) / "database") / "origenerator.db")
    put_rows(db, rows)
    return db


def database_of(newest_first: Iterable[dict] = (), *,
                kind: type[Database] = Database) -> Database:
    return database_in(THIS_TESTS_FOLDER / "databases", reversed(list(newest_first)), kind=kind)


def keep_rows_on_disk(monkeypatch) -> None:
    monkeypatch.setattr(sys.modules[__name__], "ROWS_KEPT_ON_DISK", True)


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
    db.insert_rows([on_disk(row) for row in rows] if ROWS_KEPT_ON_DISK else rows)


def keep_on_disk(db: Database) -> None:
    for row in db.list_generations():
        if (files := json.loads(row.get("output_files") or "[]")) and "path" not in files[0]:
            kept_on_disk(db, row, kept_file(files[0]["filename"]))


def on_disk(row: dict) -> dict:
    files = json.loads(row.get("output_files") or "[]")
    if not files:
        return row
    return {**row, "output_files": _named_on_disk(files, kept_file(files[0]["filename"]))}


def kept_file(filename: str) -> Path:
    return THIS_TESTS_FOLDER / "kept" / filename


def kept_on_disk(db: Database, row: dict, path: Path) -> dict:
    files = json.loads(row.get("output_files") or "[]") or [{"filename": path.name}]
    db.update_generation(row["prompt_id"], output_files=_named_on_disk(files, path))
    return db.get_generation(row["prompt_id"])


def _named_on_disk(files: list[dict], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _write_a_stand_in(path)
    return json.dumps([{**files[0], "path": str(path)}, *files[1:]])


def _write_a_stand_in(path: Path) -> None:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        Image.new("RGB", (4, 4), "gray").save(path)
    else:
        path.write_bytes(b"kept")
