from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from app_support.watch_weights import NEUTRAL_WEIGHT, recorded_weight

from origenerator.config import LIBRARY_ROOT
from origenerator.evolver_agreement import evolver_checkout, records_folder
from origenerator.media import MediaType, media_type_from_filename


class RecordedWeights:
    def __init__(self, records_folder: Path | None, *,
                 read: Callable[[Path, Path | None], float] = recorded_weight) -> None:
        self._records_folder = records_folder
        self._read = read
        self._known: dict[str, float] = {}

    def of(self, item) -> float:
        video = str(item)
        if media_type_from_filename(video) != MediaType.VIDEO:
            return NEUTRAL_WEIGHT
        if video not in self._known:
            self._known[video] = self._read(Path(item), self._records_folder)
        return self._known[video]

    def learn(self, items: Iterable) -> None:
        for item in items:
            self.of(item)


def of_this_library() -> dict[str, Callable]:
    weights = RecordedWeights(records_folder(evolver_checkout(), LIBRARY_ROOT))
    return {"weight_of": weights.of, "learn_weights": weights.learn}
