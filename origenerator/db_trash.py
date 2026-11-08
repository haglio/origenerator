from __future__ import annotations

import json
from pathlib import Path

from origenerator.db_connection import Store
from origenerator.db_generations import library_paths_in
from origenerator.db_schema import as_read
from origenerator.generation_state import GenerationSource, source_of
from origenerator.trash import TrashedBatch


class TrashStore(Store):

    def record_trashed(self, prompt_id: str, row: dict, batch: dict, *,
                        deleted_at: str | None = None):
        with self._connect() as conn:
            if deleted_at is not None:
                conn.execute("UPDATE deletions SET row_json = ?, batch_json = ? WHERE prompt_id = ?",
                             (json.dumps(row, default=str), json.dumps(batch), prompt_id))
                return
            conn.execute(
                "INSERT OR REPLACE INTO deletions (prompt_id, row_json, batch_json)"
                " VALUES (?, ?, ?)",
                (prompt_id, json.dumps(row, default=str), json.dumps(batch)),
            )

    def list_trashed(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompt_id, row_json, batch_json, deleted_at FROM deletions"
                " ORDER BY deleted_at DESC, rowid DESC"
            ).fetchall()
            return [trashed for r in rows if _of_a_known_source(trashed := _trashed_record(r))]

    def get_trashed(self, prompt_id: str) -> dict | None:
        with self._connect() as conn:
            record = conn.execute(
                "SELECT prompt_id, row_json, batch_json, deleted_at FROM deletions"
                " WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()
            trashed = _trashed_record(record) if record else None
            return trashed if trashed is not None and _of_a_known_source(trashed) else None

    def trashed_file(self, original: Path) -> Path | None:
        with self._connect() as conn:
            batches = conn.execute("SELECT batch_json FROM deletions"
                                   " ORDER BY deleted_at DESC, rowid DESC").fetchall()
        held = (TrashedBatch.from_record(json.loads(batch[0])).holding(original) for batch in batches)
        return next((file for file in held if file is not None and file.is_file()), None)

    def trashed_library_paths(self) -> set[str]:
        with self._connect() as conn:
            held = conn.execute("SELECT row_json FROM deletions"
                                " WHERE row_json LIKE '%library_path%'").fetchall()
        return {path for record in held
                for path in library_paths_in(json.loads(record[0]).get("output_files"))}

    def forget_trashed(self, prompt_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM deletions WHERE prompt_id = ?", (prompt_id,))


def _of_a_known_source(trashed: dict) -> bool:
    return source_of(trashed["row"]) in GenerationSource


def _trashed_record(record) -> dict:
    return {
        "prompt_id": record["prompt_id"],
        "row": as_read(json.loads(record["row_json"])),
        "batch": json.loads(record["batch_json"]),
        "deleted_at": record["deleted_at"],
    }
