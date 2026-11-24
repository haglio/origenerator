from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator import gallery, trash_collection
from origenerator.gallery.output import is_in_progress
from origenerator.gallery.tree import is_an_enhance_being_made
from origenerator.library_views import LibrarySnapshot


class Read(NamedTuple):
    rows: list[dict]
    meta: dict
    requests: list[dict]
    fingerprint: tuple[int, int]
    version: int | None = None


def read_whole(db, last: Read | None = None) -> Read:
    version = db.library_version()
    if last is not None and last.version == version:
        return last
    rows = db.list_generations()
    meta = db.folder_meta_map()
    return Read(rows, meta, db.list_requests(), _fingerprint(rows, meta), version)


class LibraryReadings:
    def __init__(self, db, item_names, publish_names: Callable[[dict[str, str]], None], *,
                 populating: Callable[[], frozenset[str]] = frozenset) -> None:
        self._db = db
        self._populating = populating
        self._item_names = item_names
        self._publish_names = publish_names
        self.reading = LibrarySnapshot([])
        self.folder_meta: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.live_ids: set[str] = set()
        self.customs_by_shape: dict[str, list] = {}
        self._shapes: tuple = ()
        self.drawn_version = 0
        self._fingerprint: tuple = (None, None)
        self._lists_built_from = None
        self._fingerprinted: tuple[list, int] | None = None

    @property
    def customs(self) -> list:
        return [folder for folders in self.customs_by_shape.values() for folder in folders]

    def read(self) -> tuple[list[dict], dict]:
        return self._db.list_generations(), self._db.folder_meta_map()

    def moved_to(self, rows, meta) -> bool:
        fingerprint = self._fingerprint_of(rows, meta)
        moved = fingerprint != self._fingerprint
        self._fingerprint = fingerprint
        return moved

    def is_news(self, read: Read, read_at: int) -> bool:
        self._fingerprinted = (read.rows, read.fingerprint[0])
        if read.fingerprint == self._fingerprint or read_at != self.drawn_version:
            return False
        self._fingerprint = read.fingerprint
        return True

    def take(self, rows, meta, shapes) -> LibrarySnapshot:
        self.folder_meta = meta
        self.drawn_version += 1
        library = self.reading = self._reading_of(rows, meta)
        self.live_ids = {row["prompt_id"] for row in library.rows}
        self._shapes = tuple(shapes)
        self.customs_by_shape = {shape: library.custom_collections(shape) for shape in shapes}
        self.requests = self._db.list_requests()
        return library

    def _fingerprint_of(self, rows, meta) -> tuple[int, int]:
        known = self._fingerprinted
        if known is None or known[0] is not rows:
            known = self._fingerprinted = (rows, _rows_fingerprint(rows))
        return known[1], _folder_meta_fingerprint(meta)

    def _reading_of(self, rows, meta) -> LibrarySnapshot:
        state = self._fingerprint_of(rows, meta)
        unmoved = state == self._lists_built_from
        library = LibrarySnapshot(rows, trash_collection.trash_items(self._db.list_trashed()),
                                  folder_meta=meta, name_of=self._item_names.of,
                                  custom_collections=self._db.list_custom_collections(),
                                  previous=self.reading,
                                  names_version=lambda: self._item_names.version,
                                  populating=self._populating)
        if not unmoved:
            self._lists_built_from = state
            self._item_names.take(library.rows, library.held_rows, library.image_index,
                                  library.readings)
            self._publish_names(self._item_names.by_file(library.rows))
        return library

    def folder_key_of(self, row: dict) -> str:
        return gallery.settings_folder_key(row, self.reading.image_index)

    def folder_key_for(self, workflow_name: str, params: dict,
                       workflow_version: str | None = None) -> str:
        return gallery.folder_key_for(workflow_name, params, self.reading.image_index,
                                      workflow_version)

    def leaf_folders(self) -> dict[str, list[dict]]:
        return self.reading.leaf_folders(self._shapes)

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
    return hash(tuple(_where_it_is_drawn(r) if is_in_progress(r) else _all_it_shows(r)
                      for r in rows if not is_an_enhance_being_made(r)))


def _where_it_is_drawn(row) -> tuple:
    return row.get("prompt_id"), row.get("workflow_name"), row.get("params_json")


def _all_it_shows(row) -> tuple:
    return (row.get("prompt_id"), row.get("status"), row.get("thumbnail_path"),
            row.get("workflow_name"), row.get("params_json"), row.get("output_files"),
            row.get("evolver_upscale"), row.get("evolver_upscaled_at"))


def _folder_meta_fingerprint(meta) -> int:
    return hash(tuple(sorted(
        (k, v.get("custom_name"), v.get("starred")) for k, v in meta.items()
    )))
