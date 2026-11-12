from __future__ import annotations

import os
from pathlib import Path

from origenerator.gallery.output import (
    generations_by_stem,
    place_of_its_own,
    row_output_files,
    stem_as_made,
)


class VideoRows:
    def __init__(self, rows: list[dict]) -> None:
        self._at = {_place(kept): row["prompt_id"] for row in reversed(rows)
                    for file in row_output_files(row) if (kept := place_of_its_own(file))}
        self._upscaled_at = {_place(row["evolver_upscale"]): row["prompt_id"]
                             for row in reversed(rows) if row.get("evolver_upscale")}
        self._by_stem = generations_by_stem(rows)

    def __call__(self, video: Path) -> str | None:
        place = _place(video)
        return (self._at.get(place) or self._upscaled_at.get(place)
                or self._by_stem.get(stem_as_made(video)))


def _place(path) -> str:
    return os.path.normcase(os.path.abspath(path))
