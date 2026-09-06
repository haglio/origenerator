"""Workflow parameter keys this app has stopped using, and their current names.

A ParamDef key is not a local name. It is written into every run's
``params_json``, into the verbatim copy of that row the recovery bin holds, and
into ``state/ui_state.json`` for every open generate tab, and it can be pinned
by hand in a curated recipe in the content overlay -- so renaming one is a
migration, and it is applied wherever those four are read back.

Nothing validates a params key set: a workflow asked for a key that is not there
falls back to its default. So a missed migration is silent, which is why this
list is history and never shrinks.
"""

from __future__ import annotations

import json

#: retired key -> the name it carries now.
RENAMED: dict[str, str] = {
    "stroke_hz": "motion_hz",
    "stroke_x": "motion_x",
    "stroke_top": "motion_ceiling",
    "stroke_bottom": "motion_floor",
}


def renamed(params: dict) -> dict:
    """``params`` with every retired key moved onto its current name."""
    if not isinstance(params, dict):
        return params
    return {RENAMED.get(key, key): value for key, value in params.items()}


def _renamed_json(raw) -> str | None:
    """``raw`` re-encoded with the keys moved, or ``None`` if nothing moved."""
    try:
        params = json.loads(raw) if raw else None
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(params, dict) or not set(params) & set(RENAMED):
        return None
    return json.dumps(renamed(params))


def _candidates(conn, table: str, column: str) -> list:
    """Rows of ``table`` whose ``column`` mentions a retired key, by rowid.

    A coarse text filter, since the bin's copy carries its params as a string
    inside a string; the decode below is what actually decides. Filtered in SQL
    all the same, so an already-migrated library decodes nothing on a launch.
    """
    tests = " OR ".join(f"{column} LIKE ?" for _ in RENAMED)
    return conn.execute(
        f"SELECT rowid, {column} FROM {table} WHERE {tests}",
        [f"%{old}%" for old in RENAMED],
    ).fetchall()


def migrate_stored_params(conn) -> None:
    """Move both stores onto the current key names.

    ``generations.params_json`` is what a re-roll, a duplicate check and the
    workflow itself read. ``deletions.row_json`` holds a whole generation row,
    ``params_json`` included, and a restore re-inserts it verbatim -- so a bin
    left unmigrated hands the old keys back the moment anything is restored.
    """
    for rowid, raw in _candidates(conn, "generations", "params_json"):
        moved = _renamed_json(raw)
        if moved is not None:
            conn.execute("UPDATE generations SET params_json = ? WHERE rowid = ?",
                         (moved, rowid))
    for rowid, raw in _candidates(conn, "deletions", "row_json"):
        try:
            row = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(row, dict):
            continue
        moved = _renamed_json(row.get("params_json"))
        if moved is not None:
            row["params_json"] = moved
            conn.execute("UPDATE deletions SET row_json = ? WHERE rowid = ?",
                         (json.dumps(row), rowid))
