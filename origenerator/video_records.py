from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Iterable
from typing import NamedTuple

from app_support.video_action import STORED_ACTIONS_KEY
from app_support.watch_weights import NEUTRAL_WEIGHT, WATCH_BLOCK, WEIGHT_KEY, weight_for
from funestra.video_groups import (
    GroupIndex,
    VideoEntry,
    action_group_items,
    normalize_path_key,
    seed_group_items,
    widened_seed_items,
)

from origenerator.db_generations import WATCH_COLUMNS
from origenerator.gallery import media_type_of_row
from origenerator.gallery.signatures import parse_params
from origenerator.gallery.source_image import start_images_among
from origenerator.generation_state import GenerationSource, source_of
from origenerator.media import MediaType, media_type_from_filename
from origenerator.video_rows import VideoRows
from origenerator.workflows.outside import PLACES

_NOTHING_FILED = VideoEntry(path="", weight=NEUTRAL_WEIGHT)


class FiledLoops(NamedTuple):
    actions: tuple[str, ...] = ()
    seeds: tuple[str, ...] = ()
    more_seeds: tuple[str, ...] = ()


def record_of_row(video: dict, start_image: dict | None) -> dict:
    shown = _recorded(video, MediaType.VIDEO)
    if video.get("action"):
        shown["action"] = video["action"]
    if labels := json.loads(video.get("combined_labels") or "[]"):
        shown[STORED_ACTIONS_KEY] = labels
    record = {"video": shown, WATCH_BLOCK: {WEIGHT_KEY: weight_for(
        {field: video.get(column) or 0 for field, column in WATCH_COLUMNS})}}
    if start_image is not None and source_of(start_image) == GenerationSource.OUTSIDE:
        record["source_image"] = _recorded(start_image, MediaType.IMAGE)
    return record


def _recorded(row: dict, made: MediaType) -> dict:
    params = parse_params(row.get("params_json"))
    return {key: params[place] for key, place in PLACES[made].items()
            if params.get(place) not in (None, "")}


class GalleryRecords:
    def __init__(self, db) -> None:
        self._db = db
        self._read_at: object = None
        self._rows: dict[str, dict] = {}
        self._row_of: Callable[[object], str | None] = VideoRows([])
        self._start_image_of: Callable[[dict], dict | None] = lambda _row: None

    def __call__(self, video) -> dict:
        self._keep_up()
        row = self._rows.get(self._row_of(video))
        return record_of_row(row, self._start_image_of(row)) if row is not None else {}

    def _keep_up(self) -> None:
        version = self._db.library_version()
        if version == self._read_at:
            return
        rows = self._db.list_generations()
        self._read_at, self._rows, self._row_of = (
            version, {row["prompt_id"]: row for row in rows}, VideoRows(rows))
        self._start_image_of = start_images_among(
            [row for row in rows if media_type_of_row(row) == MediaType.IMAGE])


class VideoRecords:
    def __init__(self, record_of: Callable[[str], dict]) -> None:
        self._record_of = record_of
        self._index = GroupIndex(entries={}, action_items={}, seed_items={})

    def _of(self, item) -> VideoEntry:
        video = str(item)
        if media_type_from_filename(video) != MediaType.VIDEO:
            return _NOTHING_FILED
        self._index.learn(video, self._record_of)
        return self._index.entry(video)

    def weight_of(self, item) -> float:
        return self._of(item).weight

    def group_of(self, item, by_seed_group: bool) -> Hashable | None:
        filed = self._of(item)
        if not by_seed_group:
            return filed.action_key
        return filed.seed_key[0] if filed.seed_key is not None else None

    def learn(self, items: Iterable) -> None:
        for item in items:
            self._of(item)

    def loops_of(self, item) -> FiledLoops:
        video = str(item)
        key = normalize_path_key(video)
        actions, seeds, widened = (
            tuple(other for other in gather(self._index, video)
                  if normalize_path_key(other) != key)
            for gather in (action_group_items, seed_group_items, widened_seed_items))
        return FiledLoops(actions, seeds,
                          more_seeds=tuple(other for other in widened if other not in seeds))


def of_this_library(db) -> dict[str, Callable]:
    records = VideoRecords(GalleryRecords(db))
    return {"weight_of": records.weight_of, "learn_weights": records.learn,
            "record_group_of": records.group_of, "record_loops_of": records.loops_of}
