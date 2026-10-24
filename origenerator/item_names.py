"""Every item's name, kept current with the library and the numbers it has handed out."""
from __future__ import annotations

from collections import defaultdict

from origenerator import gallery
from origenerator.gallery.item_numbers import item_name, number_items
from origenerator.gallery.tree import placeable_rows
from origenerator.recovery import bin_items


class ItemNames:

    def __init__(self, numbers):
        self._numbers = numbers
        self._names: dict[str, str] = {}
        self._wearing: dict[str, str] = {}

    @classmethod
    def from_library(cls, db) -> ItemNames:
        rows = db.list_generations()
        names = cls(db)
        names.take(rows, bin_items(db.list_deletions()), gallery.start_frame_index(rows))
        return names

    def take(self, rows: list[dict], held_rows: list[dict], image_index: dict) -> None:
        folders: dict[str, list[str]] = defaultdict(list)
        for row in _items_oldest_first(rows, held_rows):
            folders[gallery.settings_folder_key(row, image_index)].append(row["prompt_id"])
        recorded = self._numbers.list_item_numbers()
        numbering = number_items(folders, recorded)
        changed = {prompt_id: item for prompt_id, item in numbering.items()
                   if recorded.get(prompt_id) != item}
        if changed:
            self._numbers.record_item_numbers(changed)
        self._names = {prompt_id: item_name(item)
                       for prompt_id, item in numbering.items()}
        self._wearing = {name: prompt_id for prompt_id, name in self._names.items()}

    def of(self, prompt_id: str | None) -> str:
        return self._names.get(prompt_id, "")

    def prompt_id_of(self, name: str) -> str | None:
        return self._wearing.get(name)


def _items_oldest_first(rows: list[dict], held_rows: list[dict]) -> list[dict]:
    items = [row for row in placeable_rows([*reversed(rows), *held_rows])
             if gallery.produced_output(row)]
    return sorted(items, key=lambda row: row.get("id") or 0)
