from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

from app_support.media_renditions import original_rendition

from origenerator import gallery, points_of_interest, trash_collection
from origenerator.config import EVOLVER_AI_DIR, EVOLVER_SOURCE, KINO_UPSCALES_DIR, OUTPUT_PLACES
from origenerator.evolver_upscales import EvolverUpscales
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
    folder_collection,
)
from origenerator.gallery.custom import index_folders
from origenerator.gallery.enhance import EnhanceVersion, file_at, upscale_and_original
from origenerator.gallery.placement import Placement
from origenerator.gallery.shapes import LANDSCAPE, shape_covers
from origenerator.gallery.tree import KeptFolders, all_the_same
from origenerator.generation_state import on_the_map
from origenerator.item_shape import filter_rows, row_shape, split_key
from origenerator.media import MediaType
from origenerator.one_look import one_look
from origenerator.row_readings import RowReadings
from origenerator.workflows.detail_parts import parts_framed_together


@dataclass(frozen=True)
class TabViews:
    heights: object = None
    names: object = None
    animated_preview: Callable[[dict], str | None] | None = None
    library: object = None
    requests: object = None


NO_VIEWS = TabViews()


class LibrarySnapshot:
    def __init__(self, rows: list[dict], held_rows: list[dict] = (), *,
                 folder_meta: dict | None = None,
                 name_of: Callable[[str], str] | None = None,
                 custom_collections: list[dict] = (),
                 previous: LibrarySnapshot | None = None,
                 names_version: Callable[[], object] = lambda: None,
                 evolvers_folder: Path = EVOLVER_AI_DIR):
        self.rows = _carried_over(rows, previous.rows if previous else ())
        self.held_rows = _carried_over(held_rows, previous.held_rows if previous else ())
        self.folder_meta = _carried_over_whole(folder_meta or {},
                                               previous.folder_meta if previous else None)
        self._name_of = name_of
        self._names_version = names_version
        self._custom_records = custom_collections
        self._evolvers_folder = evolvers_folder
        self._customs: dict[str, list] = {}
        self._ids_at: dict[str | None, frozenset[str]] = {}
        self._slides: dict[tuple, tuple | None] = {}
        self._versions: dict[tuple, tuple | None] = {}
        self._in_settings: dict[tuple[str, str], list[dict]] = {}
        self._on_the_map: dict[str | None, list[dict]] = {}
        self.readings = RowReadings(previous.readings if previous else None)
        self._drawn_before = previous.drawn() if previous else {}
        self._image_index_before = previous.image_index if previous else None
        self._unmoved = (previous is not None and all_the_same(self.rows, previous.rows)
                         and self.folder_meta is previous.folder_meta)
        self._drawn: dict[str, tuple[KeptFolders, list]] = {}
        self._image_index: dict | None = None
        self._placements: dict[str | None, Placement] = {}
        self._on_shape: dict[tuple[str | None, str | None], list[dict]] = {}

    @property
    def image_index(self) -> dict:
        if self._image_index is None:
            before = self._image_index_before
            self._image_index = before if self._unmoved else _carried_over_whole(
                self._start_frames(), before)
        return self._image_index

    def tree(self, shape: str) -> list:
        if shape not in self._drawn:
            before = self._drawn_before.get(shape)
            drawn_with = (self.folder_meta, self._names_version())
            if self._unmoved and before is not None and all_the_same(before[0].drawn_with,
                                                                     drawn_with):
                self._drawn[shape] = before
            else:
                kept = KeptFolders(before[0] if before else None, drawn_with=drawn_with)
                self._drawn[shape] = (kept, gallery.build_gallery_tree(
                    self._on_the_shape(self.rows, shape), self.folder_meta,
                    image_index=self.image_index, name_of=self._name_of, kept=kept))
        return self._drawn[shape][1]

    def drawn(self) -> dict[str, tuple[KeptFolders, list]]:
        return {**(self._drawn_before if self._unmoved else {}), **self._drawn}

    @cached_property
    def rows_by_id(self) -> dict[str, dict]:
        return {row["prompt_id"]: row for row in self.rows}

    def row_for(self, prompt_id: str) -> dict | None:
        row = self.rows_by_id.get(prompt_id)
        if row is not None:
            return row
        return next((held for held in self.held_rows if held["prompt_id"] == prompt_id), None)

    @property
    def favorite_ids(self) -> set[str]:
        return {row["prompt_id"] for row in self.rows if row.get("starred")}

    @cached_property
    def image_rows(self) -> list[dict]:
        return self._of_kind(MediaType.IMAGE)

    @cached_property
    def video_rows(self) -> list[dict]:
        return self._of_kind(MediaType.VIDEO)

    @cached_property
    def recency(self) -> dict:
        return gallery.enhancement_recency(self.rows)

    @cached_property
    def recent_rows(self) -> list[dict]:
        return gallery.recent_generations(self.rows, bumped=self.recency)

    @cached_property
    def enhanced_rows(self) -> list[dict]:
        return self._each_alone(gallery.enhanced_generations, "enhanced")

    @cached_property
    def experiment_rows(self) -> list[dict]:
        return self._each_alone(gallery.unreviewed_experiments, "experiment")

    def _each_alone(self, keep, reading: str) -> list[dict]:
        kept = self.readings.of(reading, lambda row: bool(keep([row])))
        return [row for row in self.rows if kept(row)]

    def _on_the_shape(self, rows, shape: str | None) -> list[dict]:
        return filter_rows(rows, shape, self.readings.of("shape", row_shape))

    def _start_frames(self) -> dict:
        frames_of = self.readings.of("start frames", lambda row: gallery.start_frame_index([row]))
        index: dict = {}
        for row in self.rows:
            for name, frame in frames_of(row).items():
                index.setdefault(name, frame)
        return index

    def on_shape(self, shape: str | None, listing: str | None = None) -> list[dict]:
        if (listing, shape) not in self._on_shape:
            self._on_shape[(listing, shape)] = self._on_the_shape(self._listing(listing), shape)
        return self._on_shape[(listing, shape)]

    def _listing(self, which: str | None) -> list[dict]:
        if which is None:
            return self.rows
        return {LATEST_KEY: self.recent_rows, ENHANCED_KEY: self.enhanced_rows,
                EXPERIMENTS_KEY: self.experiment_rows, TRASH_KEY: self.held_rows}[which]

    def placement(self, shape: str | None) -> Placement:
        if shape not in self._placements:
            self._placements[shape] = Placement(gallery.all_group(self.tree(shape)),
                                                self.image_index)
        return self._placements[shape]

    def custom_collections(self, shape: str) -> list:
        if shape not in self._customs:
            self._customs[shape] = gallery.build_custom_collections(
                self.tree(shape), [record for record in self._custom_records
                                   if shape_covers(shape, record["side"] or LANDSCAPE)])
        return self._customs[shape]

    def folder(self, key: str | None):
        base, shape = split_key(key)
        placed = self.placement(shape).folder(base)
        if placed is not None:
            return placed
        return index_folders(self.custom_collections(shape)).get(base) if shape else None

    def rows_at(self, key: str | None) -> list[dict]:
        base, shape = split_key(key)
        collection = folder_collection(base)
        if collection is not None:
            return self.in_collection(collection.which, shape, collection.folder)
        folder = self.folder(key)
        return gallery.rows_under(folder) if folder is not None else []

    @cached_property
    def upscales(self) -> EvolverUpscales:
        return EvolverUpscales.scan(KINO_UPSCALES_DIR, EVOLVER_SOURCE)

    def slides_of(self, rows) -> list[tuple]:
        with one_look():
            slides = [self._once(self._slides, row, self._slide_of) for row in rows]
        return [slide for slide in slides if slide is not None]

    def versions_of(self, rows) -> dict[str, list]:
        with one_look():
            playlists = [self._once(self._versions, row, self._versions_of_one) for row in rows]
        return dict(playlist for playlist in playlists if playlist is not None)

    @staticmethod
    def _once(kept: dict, row: dict, work_out):
        key = (row["prompt_id"], row.get("output_files"), row.get("thumbnail_path"))
        if key not in kept:
            kept[key] = work_out(row)
        return kept[key]

    def _slide_of(self, row: dict) -> tuple | None:
        resolved = gallery.resolve_preview(row, OUTPUT_PLACES)
        if resolved is None:
            return None
        path, media_type = resolved
        return (self.upscales.upscale_of(path) or path, media_type, row["prompt_id"],
                row.get("thumbnail_path"))

    def _versions_of_one(self, row: dict) -> tuple | None:
        media_type = gallery.media_type_of_row(row)
        resolved = (gallery.resolve_preview(row, OUTPUT_PLACES)
                    if media_type == MediaType.VIDEO else None)
        upscale = self.upscales.upscale_of(resolved[0]) if resolved is not None else None
        versions = (gallery.displayed_versions(row, upscale)
                    or self._beside_its_original(resolved))
        if len(versions) <= 1:
            return None
        framed_together = parts_framed_together()
        entries = [Version(gallery.output_file_path(version.file, OUTPUT_PLACES), media_type,
                           version.label,
                           points_of_interest.boxes_of(version.file, framed_together=framed_together))
                   for version in versions]
        return str(entries[0].path), entries

    def _beside_its_original(self, resolved) -> list[EnhanceVersion]:
        original = (original_rendition(resolved[0], self._evolvers_folder)
                    if resolved is not None else "")
        if not original:
            return []
        return upscale_and_original(file_at(Path(resolved[0])), file_at(Path(original)))

    def ids_at(self, key: str | None) -> frozenset[str]:
        if key not in self._ids_at:
            self._ids_at[key] = frozenset(row["prompt_id"] for row in self.rows_at(key))
        return self._ids_at[key]

    def in_collection(self, which: str, shape: str | None, folder: str) -> list[dict]:
        placement = self.placement(shape)
        if which == FAVORITES_KEY:
            group = placement.folder(folder)
            starred_folders = gallery.favorite_folders(gallery.child_groups(group)) if group else []
            return _each_once([
                *placement.held_by(folder, gallery.favorite_generations(self.on_shape(shape))),
                *(row for starred in starred_folders for row in gallery.rows_under(starred))])
        return placement.held_by(folder, self.on_shape(shape, which))

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
            self._on_the_map[shape] = self._on_the_shape(
                [row for row in self.rows if on_the_map(row)], shape)
        return self._on_the_map[shape]

    def _of_kind(self, kind: MediaType) -> list[dict]:
        return [row for row in self.rows if gallery.media_type_of_row(row) == kind]


class Version(NamedTuple):
    path: object
    media_type: str
    label: str = ""
    points_of_interest: tuple = ()


def _carried_over(rows, before) -> list[dict]:
    if not before:
        return rows
    read_before = {row["prompt_id"]: row for row in before}
    return [kept if (kept := read_before.get(row["prompt_id"])) is not None and kept == row
            else row for row in rows]


def _carried_over_whole(reading, before):
    return before if before is not None and before == reading else reading


def _each_once(rows) -> list[dict]:
    first: dict[str, dict] = {}
    for row in rows:
        first.setdefault(row["prompt_id"], row)
    return list(first.values())


class LibraryViews:
    def __init__(self, db):
        self._db = db
        self._version: int | None = None
        self._snapshot: LibrarySnapshot | None = None

    def now(self) -> LibrarySnapshot:
        version = self._db.library_version()
        if self._snapshot is None or version != self._version:
            self._version = version
            self._snapshot = LibrarySnapshot(
                self._db.list_generations(),
                trash_collection.trash_items(self._db.list_trashed()))
        return self._snapshot
