from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
from typing import NamedTuple

from origenerator import gallery, points_of_interest, trash_collection
from origenerator.config import EVOLVER_SOURCE, EVOLVER_UPSCALED_DIR, OUTPUT_PLACES
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
from origenerator.gallery.placement import Placement
from origenerator.gallery.shapes import LANDSCAPE, shape_covers
from origenerator.generation_state import on_the_map
from origenerator.item_shape import filter_rows, split_key
from origenerator.media import MediaType
from origenerator.one_look import one_look
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
                 trees_from: LibrarySnapshot | None = None):
        self.rows = rows
        self.held_rows = held_rows
        self.folder_meta = folder_meta or {}
        self._name_of = name_of
        self._custom_records = custom_collections
        self._customs: dict[str, list] = {}
        self._ids_at: dict[str | None, frozenset[str]] = {}
        self._slides: dict[tuple, tuple | None] = {}
        self._versions: dict[tuple, tuple | None] = {}
        self._in_settings: dict[tuple[str, str], list[dict]] = {}
        self._on_the_map: dict[str | None, list[dict]] = {}
        self._trees: dict[str, list] = dict(trees_from.trees) if trees_from else {}
        self._image_index: dict | None = trees_from.image_index if trees_from else None
        self._placements: dict[str | None, Placement] = {}
        self._on_shape: dict[tuple[str | None, str | None], list[dict]] = {}

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
        return gallery.enhanced_generations(self.rows)

    @cached_property
    def experiment_rows(self) -> list[dict]:
        return gallery.unreviewed_experiments(self.rows)

    def on_shape(self, shape: str | None, listing: str | None = None) -> list[dict]:
        if (listing, shape) not in self._on_shape:
            self._on_shape[(listing, shape)] = filter_rows(self._listing(listing), shape)
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
        return EvolverUpscales.scan(EVOLVER_UPSCALED_DIR, EVOLVER_SOURCE)

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
        versions = gallery.displayed_versions(row, upscale)
        if len(versions) <= 1:
            return None
        framed_together = parts_framed_together()
        entries = [Version(gallery.output_file_path(version.file, OUTPUT_PLACES), media_type,
                           version.label,
                           points_of_interest.boxes_of(version.file, framed_together=framed_together))
                   for version in versions]
        return str(entries[0].path), entries

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
            self._on_the_map[shape] = filter_rows(
                [row for row in self.rows if on_the_map(row)], shape)
        return self._on_the_map[shape]

    def _of_kind(self, kind: MediaType) -> list[dict]:
        return [row for row in self.rows if gallery.media_type_of_row(row) == kind]


class Version(NamedTuple):
    path: object
    media_type: str
    label: str = ""
    points_of_interest: tuple = ()


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
