from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple

from origenerator import gallery
from origenerator.gallery.item_numbers import item_name, number_items
from origenerator.gallery.non_ai import recorded_title
from origenerator.gallery.output import stems_made_as
from origenerator.gallery.tree import rows_with_a_folder
from origenerator.row_readings import RowReadings
from origenerator.trash_collection import trash_items


class Naming(NamedTuple):
    names: dict[str, str]
    wearing: dict[str, str]
    numbers_to_record: dict
    version: int

    def of(self, prompt_id: str | None) -> str:
        return self.names.get(prompt_id, "")


class ItemNames:

    def __init__(self, numbers):
        self._numbers = numbers
        self._names: dict[str, str] = {}
        self._wearing: dict[str, str] = {}
        self.version = 0

    @classmethod
    def from_library(cls, db) -> ItemNames:
        rows = db.list_generations()
        names = cls(db)
        names.take(rows, trash_items(db.list_trashed()), gallery.start_frame_index(rows))
        return names

    def take(self, rows: list[dict], held_rows: list[dict], image_index: dict,
             readings: RowReadings | None = None) -> None:
        self.adopt(self.work_out(rows, held_rows, image_index, readings))

    def work_out(self, rows: list[dict], held_rows: list[dict], image_index: dict,
                 readings: RowReadings | None = None) -> Naming:
        readings = readings or RowReadings()
        video_of_frame = _videos_of_starting_frames(rows, held_rows, readings.looking_up(
            "source image", gallery.source_image_id_in, image_index))
        folder_of = readings.looking_up("settings folder", gallery.settings_folder_key,
                                        image_index)
        folders: dict[str, list[str]] = defaultdict(list)
        for row in _items_oldest_first(rows, held_rows):
            if row["prompt_id"] not in video_of_frame and recorded_title(row) is None:
                folders[folder_of(row)].append(row["prompt_id"])
        recorded = self._numbers.list_item_numbers()
        numbering = number_items(folders, recorded)
        on_its_way = {row["prompt_id"] for row in rows if gallery.is_in_progress(row)}
        changed = {prompt_id: item for prompt_id, item in numbering.items()
                   if recorded.get(prompt_id) != item and prompt_id not in on_its_way}
        names = {prompt_id: item_name(item) for prompt_id, item in numbering.items()}
        names.update({row["prompt_id"]: title for row in rows
                      if (title := recorded_title(row)) is not None})
        wearing = {name: prompt_id for prompt_id, name in names.items()}
        names.update({frame: names[video] for frame, video in video_of_frame.items()
                      if video in names})
        named_before = self._names
        return Naming(names, wearing, changed,
                      self.version if names == named_before else self.version + 1)

    def adopt(self, naming: Naming) -> None:
        if naming.numbers_to_record:
            self._numbers.record_item_numbers(naming.numbers_to_record)
        self._names = naming.names
        self._wearing = naming.wearing
        self.version = naming.version

    def of(self, prompt_id: str | None) -> str:
        return self._names.get(prompt_id, "")

    def prompt_id_of(self, name: str) -> str | None:
        return self._wearing.get(name)

    def by_file(self, rows: list[dict]) -> dict[str, str]:
        return {stem: name for row in rows if (name := self.of(row["prompt_id"]))
                for stem in stems_made_as(row)}


def _videos_of_starting_frames(rows: list[dict], held_rows: list[dict],
                               source_image_of) -> dict[str, str]:
    row_of = {row["prompt_id"]: row for row in rows}
    videos: dict[str, str] = {}
    for video in [*rows, *held_rows]:
        frame = row_of.get(source_image_of(video))
        if frame is not None and gallery.was_taken_from(frame, video):
            videos.setdefault(frame["prompt_id"], video["prompt_id"])
    return videos


def _items_oldest_first(rows: list[dict], held_rows: list[dict]) -> list[dict]:
    items = [row for row in rows_with_a_folder([*reversed(rows), *held_rows])
             if gallery.produced_output(row) or gallery.is_in_progress(row)]
    return sorted(items, key=lambda row: (row.get("created_at") or "", row.get("id") or 0))
