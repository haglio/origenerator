"""Synthesize the funscript that rides alongside a generated video, and find it.

What a ``.funscript`` document is -- its keys, the metadata block an outside
player reads, what a document listing no actions answers -- belongs to every app
in this family that reads or writes one and lives in
:mod:`app_support.funscript`. Origenerator's videos carry no explicit
motion track — the diffusion model's motion lives only in the pixels — so rather than
measuring the finished video, this authors a motion *with* it from what the generation
already knows: the video's duration. The result is a rhythm, not a
pixel-accurate script; the whole generator is one function so a later swap to a
measured (FunGen) or authored (ATI) source touches nothing else.

The scripts have a folder of their own -- ``<output dir>/funscript`` -- laid out
like the output folder around it, each script named for its video's whole
filename, so no two videos share one.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app_support.funscript import document, read_actions, write

from origenerator.evolver_upscales import original_stem
from origenerator.media import VIDEO_EXTS

logger = logging.getLogger(__name__)


#: Where the scripts live, under the ComfyUI output dir.
FUNSCRIPT_SUBFOLDER = "funscript"

#: This app's name on the scripts it authors.
CREATOR = "origenerator"


def funscript_path_for(video_path, *, output_dir) -> Path:
    """``output_dir`` has no default: one read at import would pin every caller
    to wherever the content overlay pointed then."""
    video = Path(video_path)
    return (Path(output_dir) / FUNSCRIPT_SUBFOLDER / _folder_within(video.parent, output_dir)
            / f"{video.name}.funscript")


def _folder_within(folder: Path, output_dir) -> Path:
    try:
        return folder.relative_to(output_dir)
    except ValueError:
        return Path()


def _filed_under(stem: str, output_dir) -> Path:
    return Path(output_dir) / FUNSCRIPT_SUBFOLDER / f"{stem}.funscript"


def _beside(video_path) -> Path:
    return Path(video_path).with_suffix(".funscript")


def funscript_of(video_path, *, output_dir) -> Path | None:
    """The script this video HAS, or ``None`` when it has none. An upscale
    Evolver made of a video has that video's."""
    original = original_stem(video_path)
    if original is not None:
        return _script_of_upscaled(original, output_dir)
    return _first_file([funscript_path_for(video_path, output_dir=output_dir),
                        _filed_under(Path(video_path).stem, output_dir),
                        _beside(video_path)])


def _first_file(paths) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def _script_of_upscaled(stem: str, output_dir) -> Path | None:
    """The upscale's own path does not say which output folder the video it was
    made from was saved in, so that video's script is looked for as if it were
    in each of them."""
    output = Path(output_dir)
    videos = [folder / f"{stem}{suffix}"
              for folder in (output.iterdir() if output.is_dir() else ())
              for suffix in sorted(VIDEO_EXTS)]
    return _first_file([*(funscript_path_for(video, output_dir=output) for video in videos),
                        _filed_under(stem, output),
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


# Anchor colors for the classic funscript-heatmap feel (mirrors sibling Nau's
# palette): idle bins read near-black, then blue -> cyan -> green -> yellow -> red
# as the average travel speed (position units per second) climbs to 500.
_HEATMAP_GRADIENT: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (10, 14, 30)),
    (100.0, (30, 70, 230)),
    (200.0, (20, 210, 210)),
    (300.0, (40, 220, 50)),
    (400.0, (235, 220, 40)),
    (500.0, (240, 40, 30)),
]


def _speed_to_color(speed: float) -> tuple[int, int, int]:
    for (s0, c0), (s1, c1) in zip(_HEATMAP_GRADIENT, _HEATMAP_GRADIENT[1:]):
        if speed <= s1:
            frac = (speed - s0) / (s1 - s0)
            return tuple(round(lo + (hi - lo) * frac) for lo, hi in zip(c0, c1))
    return _HEATMAP_GRADIENT[-1][1]


def heatmap_colors(actions: list[dict], buckets: int) -> list[tuple[int, int, int]]:
    """One ``(r, g, b)`` per equal time bucket of ``[0, last action]``, colored by
    the average travel speed in that bucket — the funscript heatmap the strip paints.

    Each segment spreads its ``|pos delta|`` over the buckets it overlaps in
    proportion to the overlap; a bucket's speed is its accumulated travel over the
    bucket length in seconds. Empty (no actions, no span, or no buckets) so the
    caller can treat "nothing to draw" and "no script" alike.
    """
    if not actions or buckets <= 0:
        return []
    end_ms = actions[-1]["at"]
    if end_ms <= 0:
        return []
    bin_ms = end_ms / buckets
    travel = [0.0] * buckets  # position units traveled inside each bucket
    for a0, a1 in zip(actions, actions[1:]):
        t0, t1 = a0["at"], a1["at"]
        if t1 <= t0:
            continue
        delta = abs(a1["pos"] - a0["pos"])
        first = max(0, int(t0 // bin_ms))
        last = min(buckets - 1, int(t1 // bin_ms))
        for b in range(first, last + 1):
            bin_start = b * bin_ms
            overlap = min(t1, bin_start + bin_ms) - max(t0, bin_start)
            travel[b] += delta * overlap / (t1 - t0)
    bin_s = bin_ms / 1000.0
    return [_speed_to_color(units / bin_s) for units in travel]


def video_duration_seconds(video_path) -> float | None:
    """Read a video's duration via OpenCV (frame count / fps), or ``None``.

    OpenCV is already a dependency (see ``thumbnail.py``) and reads the container
    header without spawning a console process, so it costs nothing at import time
    when kept lazy here.
    """
    import cv2  # noqa: PLC0415 (heavy; the pure helpers must not pull it in)

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        cap.release()
    if fps and fps > 0 and frames and frames > 0:
        return frames / fps
    return None


def synthesize_funscript(video_path, *, hz: float, output_dir,
                         duration_provider=video_duration_seconds) -> Path | None:
    duration = duration_provider(video_path)
    if not duration or duration <= 0:
        logger.warning("No readable duration for %s; skipping funscript", video_path)
        return None
    actions = synthesize_actions(duration, hz=hz)
    if not actions:
        return None
    dest = funscript_path_for(video_path, output_dir=output_dir)
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
