from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator import trash_collection
from origenerator.gallery.tree import is_an_enhance_being_made
from origenerator.library_views import LibrarySnapshot


class Read(NamedTuple):
    rows: list[dict]
    meta: dict
    requests: list[dict]
    fingerprint: tuple[int, int]


def read_whole(db) -> Read:
    rows = db.list_generations()
    meta = db.folder_meta_map()
    return Read(rows, meta, db.list_requests(), _fingerprint(rows, meta))


class LibraryReadings:
    def __init__(self, db, item_names, publish_names: Callable[[dict[str, str]], None]) -> None:
        self._db = db
        self._item_names = item_names
        self._publish_names = publish_names
        self.reading = LibrarySnapshot([])
        self.folder_meta: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.live_ids: set[str] = set()
        self.customs_by_shape: dict[str, list] = {}
        self.drawn_version = 0
        self._fingerprint: tuple = (None, None)
        self._lists_built_from = None

    @property
    def customs(self) -> list:
        return [folder for folders in self.customs_by_shape.values() for folder in folders]

    def read(self) -> tuple[list[dict], dict]:
        return self._db.list_generations(), self._db.folder_meta_map()

    def moved_to(self, rows, meta) -> bool:
        fingerprint = _fingerprint(rows, meta)
        moved = fingerprint != self._fingerprint
        self._fingerprint = fingerprint
        return moved

    def is_news(self, read: Read, read_at: int) -> bool:
        if read.fingerprint == self._fingerprint or read_at != self.drawn_version:
            return False
        self._fingerprint = read.fingerprint
        return True

    def take(self, rows, meta, shapes) -> LibrarySnapshot:
        self.folder_meta = meta
        self.drawn_version += 1
        library = self.reading = self._reading_of(rows, meta)
        self.live_ids = {row["prompt_id"] for row in library.rows}
        self.customs_by_shape = {shape: library.custom_collections(shape) for shape in shapes}
        self.requests = self._db.list_requests()
        return library

    def _reading_of(self, rows, meta) -> LibrarySnapshot:
        state = _fingerprint(rows, meta)
        unmoved = state == self._lists_built_from
        library = LibrarySnapshot(rows, trash_collection.trash_items(self._db.list_trashed()),
                                  folder_meta=meta, name_of=self._item_names.of,
                                  custom_collections=self._db.list_custom_collections(),
                                  previous=self.reading,
                                  names_version=lambda: self._item_names.version)
        if not unmoved:
            self._lists_built_from = state
            self._item_names.take(library.rows, library.held_rows, library.image_index,
                                  library.readings)
            self._publish_names(self._item_names.by_file(library.rows))
        return library

    def folder_meta_edited(self) -> None:
        self._fingerprint = (self._fingerprint[0], _folder_meta_fingerprint(self.folder_meta))
        self.drawn_version += 1

    def row_for(self, prompt_id: str) -> dict | None:
        row = self._db.get_generation(prompt_id)
        if row:
            return row
        return next((held for held in self.reading.held_rows
                     if held["prompt_id"] == prompt_id), None)


def arrived(rows, before) -> list[dict]:
    upscale_before = {row["prompt_id"]: row.get("evolver_upscale") for row in before}
    return [row for row in rows if row["prompt_id"] not in upscale_before
            or upscale_before[row["prompt_id"]] != row.get("evolver_upscale")]


def _fingerprint(rows, meta) -> tuple[int, int]:
    return _rows_fingerprint(rows), _folder_meta_fingerprint(meta)


def _rows_fingerprint(rows) -> int:
    return hash(tuple(
        (r.get("prompt_id"), r.get("status"), r.get("thumbnail_path"),
         r.get("workflow_name"), r.get("params_json"), r.get("output_files"),
         r.get("evolver_upscale"), r.get("evolver_upscaled_at"))
        for r in rows if not is_an_enhance_being_made(r)
    ))


def _folder_meta_fingerprint(meta) -> int:
    return hash(tuple(sorted(
        (k, v.get("custom_name"), v.get("starred")) for k, v in meta.items()
    )))
