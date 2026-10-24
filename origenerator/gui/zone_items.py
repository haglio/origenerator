"""What a drop zone holds, read for it: what a dragged item lends it, the
pictures and name of what it holds, and the item a pasted name means."""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

from origenerator import gallery
from origenerator.file_refs import reference_basename, reference_path, unannotated
from origenerator.media import MediaType, media_type_from_filename
from origenerator.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)


class FilesOnly:
    """A zone with no gallery around it: files alone, a picture shown as itself."""

    def __init__(self, *, output_dir: Path, input_dir: Path):
        self._output_dir = output_dir
        self._input_dir = input_dir

    def lends(self, prompt_id: str, kind: MediaType) -> str | None:
        return None

    def item_of(self, held: str) -> str | None:
        return None

    def named(self, name: str) -> str | None:
        return None

    def name_of(self, held: str) -> str:
        return reference_basename(unannotated(held))

    def preview(self, held: str) -> tuple[str | None, str | None]:
        path = self.path_of(held)
        if path is None or media_type_from_filename(path.name) != MediaType.IMAGE:
            return (None, None)
        return (str(path), None)

    def path_of(self, held: str) -> Path | None:
        return reference_path(held, output_dir=self._output_dir, input_dir=self._input_dir)


class ZoneItems(FilesOnly):
    """The gallery's reading: a generation's own pictures and name where the
    held value names one of its files, a still made for a video from outside."""

    def __init__(self, db, names, rows_of: Callable[[MediaType], list[dict]], *,
                 output_dir: Path, input_dir: Path, thumb_dir: Path):
        super().__init__(output_dir=output_dir, input_dir=input_dir)
        self._db = db
        self._names = names
        self._rows_of = rows_of
        self._thumb_dir = thumb_dir

    def lends(self, prompt_id: str, kind: MediaType) -> str | None:
        row = self._db.get_generation(prompt_id)
        if row is None or gallery.media_type_of_row(row) != kind:
            return None
        files = gallery.row_output_files(row)
        if kind == MediaType.IMAGE:
            return gallery.output_file_reference(files)
        return next((str(gallery.output_file_path(file, self._output_dir))
                     for file in files if file.get("filename")), None)

    def item_of(self, held: str) -> str | None:
        row = self._row_of(held)
        return row["prompt_id"] if row is not None else None

    def named(self, name: str) -> str | None:
        return self._names.prompt_id_of(name)

    def name_of(self, held: str) -> str:
        row = self._row_of(held)
        return self._names.of(row["prompt_id"]) if row is not None else super().name_of(held)

    def preview(self, held: str) -> tuple[str | None, str | None]:
        row = self._row_of(held)
        if row is not None:
            return (row.get("thumbnail_path"),
                    gallery.animated_preview_path(row, self._output_dir, self._thumb_dir))
        path = self.path_of(held)
        if path is not None and media_type_from_filename(path.name) == MediaType.VIDEO:
            return (self._still_of(path), None)
        return super().preview(held)

    def _row_of(self, held: str) -> dict | None:
        path = self.path_of(held)
        kind = media_type_from_filename(path.name) if path is not None else None
        if kind is None:
            return None
        prompt_id = gallery.generation_of_file(path, self._rows_of(kind))
        return self._db.get_generation(prompt_id) if prompt_id else None

    def _still_of(self, path: Path) -> str | None:
        key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
        try:
            return str(generate_thumbnail(path, MediaType.VIDEO, self._thumb_dir,
                                          name=f"file-{key}"))
        except Exception as error:
            logger.warning("No still for %s: %s", path, error)
            return None
