from __future__ import annotations

from pathlib import Path

from app_support.funscript import (
    script_of,
    script_under_its_whole_filename,
    scripts_tree_in,
)
from funestra.funscript import Funscript
from funestra.heatmap import build_heatmap

from origenerator.evolver_upscales import original_stem
from origenerator.media import VIDEO_EXTS, video_header
from origenerator.one_look import is_file
from origenerator.output_places import OutputPlaces


def funscript_path_for(video_path, *, places: OutputPlaces) -> Path:
    video = Path(video_path)
    return (script_under_its_whole_filename(video, videos=places.videos, scripts=places.scripts)
            or places.scripts / (places.subfolder_of(video.parent) or "") / f"{video.name}.funscript")


def _filed_under(stem: str, places: OutputPlaces) -> Path:
    return places.scripts / f"{stem}.funscript"


def _beside(video_path) -> Path:
    return Path(video_path).with_suffix(".funscript")


def funscript_of(video_path, *, places: OutputPlaces) -> Path | None:
    original = original_stem(video_path)
    if original is not None:
        return _script_of_upscaled(original, places) or _filed_in_the_library(video_path, places)
    return _first_file([funscript_path_for(video_path, places=places),
                        _filed_under(Path(video_path).stem, places),
                        _beside(video_path)])


def _filed_in_the_library(video_path, places: OutputPlaces) -> Path | None:
    if places.library is None:
        return None
    return _first_file(_filed_in(Path(video_path), places.library,
                                 scripts_tree_in(places.library.parent)))


def _filed_in(video: Path, library: Path, scripts_tree: Path) -> list[Path]:
    filed = script_of(video, library=library, scripts_tree=scripts_tree)
    return [] if filed is None else [filed]


def _first_file(paths) -> Path | None:
    return next((path for path in paths if is_file(path)), None)


def _script_of_upscaled(stem: str, places: OutputPlaces) -> Path | None:
    videos = [folder / f"{stem}{suffix}"
              for folder in places.video_folders()
              for suffix in sorted(VIDEO_EXTS)]
    return _first_file([*(funscript_path_for(video, places=places) for video in videos),
                        _filed_under(stem, places),
                        *(_beside(video) for video in videos)])


def heatmap_colors(actions: list[dict], buckets: int) -> list[tuple[int, int, int]]:
    if not actions or buckets <= 0 or actions[-1]["at"] <= 0:
        return []
    script = Funscript(actions=[(action["at"], action["pos"]) for action in actions])
    return build_heatmap(script, buckets, start_ms=0, end_ms=actions[-1]["at"])


def video_duration_seconds(video_path) -> float | None:
    header = video_header(video_path)
    return header.seconds if header else None
