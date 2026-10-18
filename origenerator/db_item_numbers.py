"""The number each item carries in its folder, kept after the item is gone."""
from __future__ import annotations

from collections.abc import Mapping

from origenerator.db_connection import Store


class ItemNumberStore(Store):

    def list_item_numbers(self) -> dict[str, tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompt_id, folder_key, number FROM item_numbers").fetchall()
        return {row["prompt_id"]: (row["folder_key"], row["number"]) for row in rows}

    def record_item_numbers(self, numbers: Mapping[str, tuple[str, int]]):
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO item_numbers (prompt_id, folder_key, number)"
                " VALUES (?, ?, ?)",
                [(prompt_id, key, number) for prompt_id, (key, number) in numbers.items()],
            )
