from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

from origenerator import gallery, trash_collection
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
    def __init__(self, rows: list[dict], trashed: Callable[[], list[dict]] = list):
        self.rows = rows
        self._trashed = trashed
        self._in_settings: dict[tuple[str, str], list[dict]] = {}

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
