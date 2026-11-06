from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from pathlib import Path
from typing import NamedTuple

from app_support.mirrored_tree import filed_record
from app_support.watch_weights import NEUTRAL_WEIGHT
from funestra.video_groups import (
    GroupIndex,
    VideoEntry,
    action_group_items,
    normalize_path_key,
    seed_family_items,
    widened_seed_items,
)

from origenerator.config import LIBRARY_ROOT
from origenerator.evolver_agreement import evolver_checkout, records_folder
from origenerator.media import MediaType, media_type_from_filename

_NOTHING_FILED = VideoEntry(path="", weight=NEUTRAL_WEIGHT)


class FiledLoops(NamedTuple):
    actions: tuple[str, ...] = ()
    seeds: tuple[str, ...] = ()
    more_seeds: tuple[str, ...] = ()


class VideoRecords:
    def __init__(self, records_folder: Path | None, *,
                 read: Callable[[Path, Path | None], dict] = filed_record) -> None:
        self._records_folder = records_folder
        self._read = read
        self._index = GroupIndex(entries={}, action_items={}, seed_items={})

    def _record_of(self, video: str) -> dict:
        return self._read(Path(video), self._records_folder)

    def _of(self, item) -> VideoEntry:
        video = str(item)
        if media_type_from_filename(video) != MediaType.VIDEO:
            return _NOTHING_FILED
        self._index.learn(video, self._record_of)
        return self._index.entry(video)

    def weight_of(self, item) -> float:
        return self._of(item).weight

    def group_of(self, item, by_seed_family: bool) -> Hashable | None:
        filed = self._of(item)
        if not by_seed_family:
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
            for gather in (action_group_items, seed_family_items, widened_seed_items))
        return FiledLoops(actions, seeds,
                          more_seeds=tuple(other for other in widened if other not in seeds))


def of_this_library() -> dict[str, Callable]:
    records = VideoRecords(records_folder(evolver_checkout(), LIBRARY_ROOT))
    return {"weight_of": records.weight_of, "learn_weights": records.learn,
            "record_group_of": records.group_of, "record_loops_of": records.loops_of}
