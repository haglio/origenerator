"""What the config tabs ask of the whole library, worked out once for each
state of it rather than once for each question."""
from __future__ import annotations

from functools import cached_property

from origenerator import gallery
from origenerator.media import MediaType


class LibrarySnapshot:
    """The library as it stood at one moment, and what is read off all of it."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self._in_settings: dict[tuple[str, str], list[dict]] = {}

    @cached_property
    def image_rows(self) -> list[dict]:
        return self._of_kind(MediaType.IMAGE)

    @cached_property
    def video_rows(self) -> list[dict]:
        return self._of_kind(MediaType.VIDEO)

    @cached_property
    def image_config_index(self) -> dict:
        return gallery.build_image_config_index(self.image_rows)

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
    """One :class:`LibrarySnapshot` at a time, replaced when the library changes."""

    def __init__(self, db):
        self._db = db
        self._version: int | None = None
        self._snapshot: LibrarySnapshot | None = None

    def now(self) -> LibrarySnapshot:
        version = self._db.library_version()
        if self._snapshot is None or version != self._version:
            self._version = version
            self._snapshot = LibrarySnapshot(self._db.list_generations())
        return self._snapshot
