from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path


def copy_the_records(db_path: Path, overlay_path: Path, into: Path) -> list[Path]:
    into.mkdir(parents=True, exist_ok=True)
    copied = []
    db_copy = into / db_path.name
    if _stale(db_copy, db_path):
        _copy_a_database_in_use(db_path, db_copy)
        copied.append(db_copy)
    overlay_copy = into / overlay_path.name
    if overlay_path.exists() and _stale(overlay_copy, overlay_path):
        shutil.copy2(overlay_path, overlay_copy)
        copied.append(overlay_copy)
    return copied


def _stale(copy: Path, source: Path) -> bool:
    return not copy.exists() or copy.stat().st_mtime < source.stat().st_mtime


def _copy_a_database_in_use(db_path: Path, to: Path) -> None:
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(to)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
