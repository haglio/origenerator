"""What a drop zone holds: what a drag lends it, its pictures and name, a pasted name's item."""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

from origenerator import gallery
from origenerator.file_refs import reference_basename, reference_path, unannotated
from origenerator.library_views import LibraryViews
from origenerator.media import MediaType, media_type_from_filename
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)


class FilesOnly:
    """A zone with no gallery around it: files alone, a picture shown as itself."""

    def __init__(self, *, places: OutputPlaces, input_dir: Path):
        self._places = places
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
        return reference_path(held, places=self._places, input_dir=self._input_dir)


class ZoneItems(FilesOnly):
    """The gallery's reading: a generation's pictures and name, or a still for an outside video."""

    def __init__(self, db, names, library: LibraryViews, *,
                 places: OutputPlaces, input_dir: Path, thumb_dir: Path,
                 moving_preview: Callable[[dict], str | None]):
        super().__init__(places=places, input_dir=input_dir)
        self._db = db
        self._names = names
        self._library = library
        self._thumb_dir = thumb_dir
        self._moving_preview = moving_preview

    def lends(self, prompt_id: str, kind: MediaType) -> str | None:
        if kind == MediaType.IMAGE:
            return gallery.input_image_reference(gallery.image_lent_by(
                prompt_id, self._db.get_generation, self._library.now().image_config_index))
        row = self._db.get_generation(prompt_id)
        if row is None or gallery.media_type_of_row(row) != kind:
            return None
        return next((str(gallery.output_file_path(file, self._places))
                     for file in gallery.row_output_files(row) if file.get("filename")), None)

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
            return (row.get("thumbnail_path"), self._moving_preview(row))
        path = self.path_of(held)
        if path is not None and media_type_from_filename(path.name) == MediaType.VIDEO:
            return (self._still_of(path), None)
        return super().preview(held)

    def _row_of(self, held: str) -> dict | None:
        library = self._library.now()
        kind = media_type_from_filename(reference_basename(unannotated(held)))
        if kind == MediaType.IMAGE:
            prompt_id = gallery.source_image_id_of(held, library.image_config_index)
        else:
            path = self.path_of(held) if kind is not None else None
            prompt_id = gallery.generation_of_file(path, library.rows_of(kind)) if path else None
        return self._db.get_generation(prompt_id) if prompt_id else None

    def _still_of(self, path: Path) -> str | None:
        key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
        try:
            return str(generate_thumbnail(path, MediaType.VIDEO, self._thumb_dir,
                                          name=f"file-{key}"))
        except Exception as error:
            logger.warning("No still for %s: %s", path, error)
            return None
