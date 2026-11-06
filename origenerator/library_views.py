from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType

from origenerator import gallery, trash_collection
from origenerator.generation_state import on_the_map
from origenerator.item_shape import filter_rows
from origenerator.media import MediaType


@dataclass(frozen=True)
class TabViews:
    heights: object = None
    names: object = None
    animated_preview: Callable[[dict], str | None] | None = None
    library: object = None
    requests: object = None


NO_VIEWS = TabViews()


class LibrarySnapshot:
    def __init__(self, rows: list[dict], trashed: Callable[[], list[dict]] = list, *,
                 folder_meta: dict | None = None,
                 name_of: Callable[[str], str] | None = None,
                 trees_from: LibrarySnapshot | None = None):
        self.rows = rows
        self._trashed = trashed
        self.folder_meta = folder_meta or {}
        self._name_of = name_of
        self._in_settings: dict[tuple[str, str], list[dict]] = {}
        self._on_the_map: dict[str | None, list[dict]] = {}
        self._trees: dict[str, list] = dict(trees_from.trees) if trees_from else {}
        self._image_index: dict | None = trees_from.image_index if trees_from else None

    @property
    def trees(self) -> Mapping[str, list]:
        return MappingProxyType(self._trees)

    @property
    def image_index(self) -> dict:
        if self._image_index is None:
            self._image_index = gallery.start_frame_index(self.rows)
        return self._image_index

    def tree(self, shape: str) -> list:
        if shape not in self._trees:
            self._trees[shape] = gallery.build_gallery_tree(
                filter_rows(self.rows, shape), self.folder_meta,
                image_index=self.image_index, name_of=self._name_of)
        return self._trees[shape]

    @cached_property
    def rows_by_id(self) -> dict[str, dict]:
        return {row["prompt_id"]: row for row in self.rows}

    @cached_property
    def favorite_ids(self) -> set[str]:
        return {row["prompt_id"] for row in self.rows if row.get("starred")}

    @cached_property
    def image_rows(self) -> list[dict]:
        return self._of_kind(MediaType.IMAGE)

    @cached_property
    def video_rows(self) -> list[dict]:
        return self._of_kind(MediaType.VIDEO)

    @cached_property
    def held_rows(self) -> list[dict]:
        return trash_collection.trash_items(self._trashed())

    @cached_property
    def image_config_index(self) -> dict:
        return gallery.build_image_config_index(self.image_rows)

    def rows_of(self, kind: MediaType) -> list[dict]:
        return self.image_rows if kind == MediaType.IMAGE else self.video_rows

    def in_settings(self, key: tuple[str, str] | None) -> list[dict]:
        if key is None:
            return []
        if key not in self._in_settings:
            self._in_settings[key] = gallery.rows_in_settings(
                self.rows, key, self.image_config_index)
        return self._in_settings[key]

    def on_the_map(self, shape: str | None) -> list[dict]:
        if shape not in self._on_the_map:
            self._on_the_map[shape] = filter_rows(
                [row for row in self.rows if on_the_map(row)], shape)
        return self._on_the_map[shape]

    def _of_kind(self, kind: MediaType) -> list[dict]:
        return [row for row in self.rows if gallery.media_type_of_row(row) == kind]


class LibraryViews:
    def __init__(self, db):
        self._db = db
        self._version: int | None = None
        self._snapshot: LibrarySnapshot | None = None

    def now(self) -> LibrarySnapshot:
        version = self._db.library_version()
        if self._snapshot is None or version != self._version:
            self._version = version
            self._snapshot = LibrarySnapshot(self._db.list_generations(),
                                             self._db.list_trashed)
        return self._snapshot
