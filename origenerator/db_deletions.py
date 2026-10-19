"""The recovery bin: what a delete is still holding, until it is not.

One of the six tables `Database` used to hold all of. Its readers are
`origenerator.recovery` and `origenerator.gallery_actions`, and neither has any
business with `generations` or the custom folders.

A deleted generation's whole row travels here, plus where in the trash its files
went, so the Trash collection can list it, put both back, or end it for good. The
record goes away when the item is restored or purged, and not otherwise —
nothing here ages out; the generations row itself is gone the moment it is
deleted, which is why the row travels here rather than staying gated by a flag.
"""
from __future__ import annotations

import json

from origenerator.db_connection import Store
from origenerator.generation_state import GenerationSource, source_of


class DeletionStore(Store):
    """The four queries over the `deletions` table."""

    def record_deletion(self, prompt_id: str, row: dict, batch: dict):
        """Hold a just-deleted ``row`` and its trash ``batch`` for recovery.

        Replaces any earlier record for the same generation, so an item deleted,
        restored, and deleted again reads as binned on the date of the *latest*
        delete rather than the first one's.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO deletions (prompt_id, row_json, batch_json)"
                " VALUES (?, ?, ?)",
                (prompt_id, json.dumps(row, default=str), json.dumps(batch)),
            )

    def list_deletions(self) -> list[dict]:
        """Every held deletion, newest first — what the Trash collection lists.

        The stamp only has second resolution, so a batch deleted together ties;
        the rowid breaks it, and an ``INSERT OR REPLACE`` takes a fresh one, so
        the order stays the order things were deleted in.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompt_id, row_json, batch_json, deleted_at FROM deletions"
                " ORDER BY deleted_at DESC, rowid DESC"
            ).fetchall()
            return [deletion for r in rows if _of_a_known_source(deletion := _deletion(r))]

    def get_deletion(self, prompt_id: str) -> dict | None:
        with self._connect() as conn:
            record = conn.execute(
                "SELECT prompt_id, row_json, batch_json, deleted_at FROM deletions"
                " WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()
            deletion = _deletion(record) if record else None
            return deletion if deletion is not None and _of_a_known_source(deletion) else None

    def forget_deletion(self, prompt_id: str):
        """Drop a held deletion — the item was restored or purged."""
        with self._connect() as conn:
            conn.execute("DELETE FROM deletions WHERE prompt_id = ?", (prompt_id,))


def _of_a_known_source(deletion: dict) -> bool:
    return source_of(deletion["row"]) in GenerationSource


def _deletion(record) -> dict:
    """One ``deletions`` row with its JSON columns parsed back into data."""
    return {
        "prompt_id": record["prompt_id"],
        "row": json.loads(record["row_json"]),
        "batch": json.loads(record["batch_json"]),
        "deleted_at": record["deleted_at"],
    }
