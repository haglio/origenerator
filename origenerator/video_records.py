from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app_support.mirrored_tree import filed_record
from app_support.watch_weights import NEUTRAL_WEIGHT, weight_of
from funestra.video_families import action_group_key, seed_group_key

from origenerator.config import LIBRARY_ROOT
from origenerator.evolver_agreement import evolver_checkout, records_folder
from origenerator.media import MediaType, media_type_from_filename


@dataclass(frozen=True)
class _Filed:
    weight: float = NEUTRAL_WEIGHT
    action_group: str | None = None
    seed_family: str | None = None


_NOTHING_FILED = _Filed()


def _filed(record: dict) -> _Filed:
    seed = seed_group_key(record)
    return _Filed(weight=weight_of(record), action_group=action_group_key(record),
                  seed_family=seed[0] if seed is not None else None)


class VideoRecords:
    def __init__(self, records_folder: Path | None, *,
                 read: Callable[[Path, Path | None], dict] = filed_record) -> None:
        self._records_folder = records_folder
        self._read = read
        self._known: dict[str, _Filed] = {}

    def _of(self, item) -> _Filed:
        video = str(item)
        if media_type_from_filename(video) != MediaType.VIDEO:
            return _NOTHING_FILED
        if video not in self._known:
            self._known[video] = _filed(self._read(Path(item), self._records_folder))
        return self._known[video]

    def weight_of(self, item) -> float:
        return self._of(item).weight

    def group_of(self, item, by_seed_family: bool) -> Hashable | None:
        filed = self._of(item)
        return filed.seed_family if by_seed_family else filed.action_group

    def learn(self, items: Iterable) -> None:
        for item in items:
            self._of(item)


def of_this_library() -> dict[str, Callable]:
    records = VideoRecords(records_folder(evolver_checkout(), LIBRARY_ROOT))
    return {"weight_of": records.weight_of, "learn_weights": records.learn,
            "record_group_of": records.group_of}
