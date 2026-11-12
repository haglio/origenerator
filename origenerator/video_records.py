from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from typing import NamedTuple

from app_support.gallery_records import GalleryReading
from app_support.watch_weights import NEUTRAL_WEIGHT
from funestra.video_groups import (
    GroupIndex,
    VideoEntry,
    action_group_items,
    normalize_path_key,
    seed_group_items,
    widened_seed_items,
)

from origenerator.media import MediaType, media_type_from_filename

_NOTHING_FILED = VideoEntry(path="", weight=NEUTRAL_WEIGHT)


class FiledLoops(NamedTuple):
    actions: tuple[str, ...] = ()
    seeds: tuple[str, ...] = ()
    more_seeds: tuple[str, ...] = ()


class GalleryRecords:
    def __init__(self, db) -> None:
        self._db = db
        self._read_at: object = None
        self._reading = GalleryReading([])

    def __call__(self, video) -> dict:
        version = self._db.library_version()
        if version != self._read_at:
            self._read_at, self._reading = version, GalleryReading(self._db.list_generations())
        row = self._reading.row_of(video)
        return self._reading.record_of(row) if row is not None else {}


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
