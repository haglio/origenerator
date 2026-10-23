"""Synthesize the funscript that rides alongside a generated video, and find it.

What a ``.funscript`` document is -- its keys, the metadata block an outside
player reads, what a document listing no actions answers -- belongs to every app
in this family that reads or writes one and lives in
:mod:`app_support.funscript`. Origenerator's videos carry no explicit
motion track — the diffusion model's motion lives only in the pixels — so rather than
measuring the finished video, this authors a motion *with* it from what the generation
already knows: the video's duration. The result is a rhythm, not a
pixel-accurate script; the whole generator is one function so a later swap to a
measured (FunGen) source touches nothing else.

The scripts have a place of their own, laid out like the folders the videos are
kept in, each script named for its video's whole filename, so no two videos
share one.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app_support.funscript import document, read_actions, write
from app_support.mirrored_tree import mirrored_path
from funestra.funscript import Funscript
from funestra.heatmap import build_heatmap

from origenerator.evolver_upscales import original_stem
from origenerator.media import VIDEO_EXTS, video_header
from origenerator.output_places import OutputPlaces

logger = logging.getLogger(__name__)


#: This app's name on the scripts it authors.
CREATOR = "origenerator"


def funscript_path_for(video_path, *, places: OutputPlaces) -> Path:
    video = Path(video_path)
    return places.scripts / (places.subfolder_of(video.parent) or "") / f"{video.name}.funscript"


def _filed_under(stem: str, places: OutputPlaces) -> Path:
    return places.scripts / f"{stem}.funscript"


def _beside(video_path) -> Path:
    return Path(video_path).with_suffix(".funscript")


def funscript_of(video_path, *, places: OutputPlaces) -> Path | None:
    """The script this video HAS, or ``None`` when it has none. An upscale
    Evolver made of a video has that video's."""
    original = original_stem(video_path)
    if original is not None:
        return _script_of_upscaled(original, places)
    return _first_file([funscript_path_for(video_path, places=places),
                        _filed_under(Path(video_path).stem, places),
                        _beside(video_path)])


def library_funscript_of(video_path, *, videos_dir, scripts_dir) -> Path | None:
    """The script a video of the library HAS, or ``None``: filed in the scripts
    tree at the video's own place under the videos tree (the family's rule,
    :mod:`app_support.mirrored_tree`), or left beside the video."""
    if not video_path:
        return None
    video = Path(video_path)
    filed = mirrored_path(video, roots=[Path(videos_dir)], mirror_root=Path(scripts_dir),
                          suffix=".funscript")
    return _first_file([*([filed] if filed is not None else []), _beside(video)])


def _first_file(paths) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def _script_of_upscaled(stem: str, places: OutputPlaces) -> Path | None:
    """The upscale's own path does not say which folder the video it was made
    from was kept in, so that video's script is looked for as if it were in
    each of them."""
    videos = [folder / f"{stem}{suffix}"
              for folder in places.video_folders()
              for suffix in sorted(VIDEO_EXTS)]
    return _first_file([*(funscript_path_for(video, places=places) for video in videos),
                        _filed_under(stem, places),
                        *(_beside(video) for video in videos)])


def synthesize_actions(duration_s: float, *, hz: float) -> list[dict]:
    duration_ms = int(round(duration_s * 1000))
    if duration_ms <= 0 or hz <= 0:
        return []
    halves = 2 * max(1, round(duration_s * hz))
    half_period_ms = duration_ms / halves
    return [
        {"at": int(round(i * half_period_ms)), "pos": 0 if i % 2 == 0 else 100}
        for i in range(halves + 1)
    ]


def write_funscript(path, actions: list[dict], *, duration_seconds: int | None = None) -> None:
    """Write ``actions`` as the family's funscript document, credited to this app.

    *duration_seconds* is the clip the script was authored for, which only a
    caller that measured it knows; without one, the script's own span answers,
    which is the closest this app can get for a motion it was handed rather
    than synthesized.
    """
    write(Path(path), document(
        actions,
        duration_seconds=_span_seconds(actions) if duration_seconds is None else duration_seconds,
        creator=CREATOR,
    ))


def _span_seconds(actions: list[dict]) -> int:
    return round(actions[-1]["at"] / 1000) if actions else 0


def heatmap_colors(actions: list[dict], buckets: int) -> list[tuple[int, int, int]]:
    """The heat strip the Funestras' scrubber paints, over ``[0, last action]``:
    empty with no actions, no span or no buckets, so the caller can treat
    "nothing to draw" and "no script" alike."""
    if not actions or buckets <= 0 or actions[-1]["at"] <= 0:
        return []
    script = Funscript(actions=[(action["at"], action["pos"]) for action in actions])
    return build_heatmap(script, buckets, start_ms=0, end_ms=actions[-1]["at"])


def video_duration_seconds(video_path) -> float | None:
    header = video_header(video_path)
    return header.seconds if header else None


def synthesize_funscript(video_path, *, hz: float, places: OutputPlaces,
                         duration_provider=video_duration_seconds) -> Path | None:
    duration = duration_provider(video_path)
    if not duration or duration <= 0:
        logger.warning("No readable duration for %s; skipping funscript", video_path)
        return None
    actions = synthesize_actions(duration, hz=hz)
    if not actions:
        return None
    dest = funscript_path_for(video_path, places=places)
    write_funscript(dest, actions, duration_seconds=round(duration))
    return dest


def resynthesize_funscript(video_path, script, *, hz: float,
                           duration_provider=video_duration_seconds) -> bool:
    written = read_actions(script)
    if not _is_synthesized(written):
        return False
    duration = duration_provider(video_path)
    todays = synthesize_actions(duration or 0.0, hz=hz)
    if not todays or todays == written:
        return False
    write_funscript(script, todays, duration_seconds=round(duration))
    return True


def _is_synthesized(actions: list[dict]) -> bool:
    if not actions or actions[0]["at"] != 0:
        return False
    if any(a["pos"] != (0 if i % 2 == 0 else 100) for i, a in enumerate(actions)):
        return False
    gaps = [b["at"] - a["at"] for a, b in zip(actions, actions[1:])]
    return not gaps or max(gaps) - min(gaps) <= 1
