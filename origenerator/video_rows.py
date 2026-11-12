from __future__ import annotations

import os
from pathlib import Path, PurePath

from app_support.comfy_file_refs import frame_name
from app_support.video_names import generation_stem

from origenerator.gallery.output import place_of_its_own, row_output_files


class VideoRows:
    def __init__(self, rows: list[dict]) -> None:
        self._at = {_place(kept): row["prompt_id"] for row in reversed(rows)
                    for file in row_output_files(row) if (kept := place_of_its_own(file))}
        self._upscaled_at = {_place(row["evolver_upscale"]): row["prompt_id"]
                             for row in reversed(rows) if row.get("evolver_upscale")}
        self._made_as = {made_as(file.get("filename")): row["prompt_id"] for row in reversed(rows)
                         for file in row_output_files(row) if file.get("filename")}

    def __call__(self, video: Path) -> str | None:
        place = _place(video)
        return (self._at.get(place) or self._upscaled_at.get(place)
                or self._made_as.get(made_as(video)))


def made_as(name) -> str:
    return generation_stem(PurePath(frame_name(str(name))).stem)


def _place(path) -> str:
    return os.path.normcase(os.path.abspath(path))
