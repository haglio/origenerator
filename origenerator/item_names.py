"""Every item's name, kept current with the library and the numbers it has handed out."""
from __future__ import annotations

from collections import defaultdict

from origenerator import gallery
from origenerator.gallery.item_numbers import item_name, number_items
from origenerator.gallery.tree import rows_with_a_folder
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
        video_of_frame = _videos_of_starting_frames(rows, held_rows, image_index)
        folders: dict[str, list[str]] = defaultdict(list)
        for row in _items_oldest_first(rows, held_rows):
            if row["prompt_id"] not in video_of_frame:
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
        self._names.update({frame: self._names[video] for frame, video in video_of_frame.items()
                            if video in self._names})

    def of(self, prompt_id: str | None) -> str:
        return self._names.get(prompt_id, "")

    def prompt_id_of(self, name: str) -> str | None:
        return self._wearing.get(name)


def _videos_of_starting_frames(rows: list[dict], held_rows: list[dict],
                               image_index: dict) -> dict[str, str]:
    row_of = {row["prompt_id"]: row for row in rows}
    videos: dict[str, str] = {}
    for video in [*rows, *held_rows]:
        frame = row_of.get(gallery.source_image_id_in(video, image_index))
        if frame is not None and gallery.was_taken_from(frame, video):
            videos.setdefault(frame["prompt_id"], video["prompt_id"])
    return videos


def _items_oldest_first(rows: list[dict], held_rows: list[dict]) -> list[dict]:
    items = [row for row in rows_with_a_folder([*reversed(rows), *held_rows])
             if gallery.produced_output(row)]
    return sorted(items, key=lambda row: (row.get("created_at") or "", row.get("id") or 0))
