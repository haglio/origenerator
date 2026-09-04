"""Synthesize and read the funscript that rides alongside a generated video.

A ``.funscript`` is a JSON file of ``{"at": <ms>, "pos": 0..100}`` actions describing
stroke motion for a haptic device (the OSR2). Origenerator's videos carry no explicit
motion track — the diffusion model's motion lives only in the pixels — so rather than
measuring the finished video, this authors a stroke *with* it from what the generation
already knows: the clip's duration, and whether it loops. The result is a rhythm, not a
pixel-accurate script; the whole generator is one function so a later swap to a
measured (FunGen) or authored (ATI) source touches nothing else.

The scripts have a folder of their own -- ``<output dir>/funscript`` -- rather
than sitting beside the clips they belong to. ComfyUI's output folder is sorted
by kind, and a script is a kind; a name is what ties one to its video. So the two
questions a caller has are separate functions: :func:`funscript_path_for` says
where a script GOES, and :func:`funscript_of` says where the one this video HAS
actually IS -- the folder, or, for every script written before the folder
existed, still beside the clip.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


#: Where the scripts live, under the ComfyUI output dir.
FUNSCRIPT_SUBFOLDER = "funscript"


def funscript_path_for(video_path, *, output_dir) -> Path:
    """Where this video's script goes: ``<output_dir>/funscript/<stem>.funscript``.

    ``output_dir`` is keyword-only and has no default. The folder cannot be
    worked out from the video's own path -- a video sits at whatever depth under
    the output dir its workflow's prefix puts it -- and a signature default would
    be read at import, from a constant itself built by reading the content
    overlay, pinning every caller to wherever this module was first told to look.
    """
    name = Path(video_path).with_suffix(".funscript").name
    return Path(output_dir) / FUNSCRIPT_SUBFOLDER / name


def legacy_funscript_path_for(video_path) -> Path:
    """Where this video's script sat before the scripts had a folder: beside it.

    Hundreds were written that way and are still there, so every read tries here
    too. Nothing writes here any more.
    """
    return Path(video_path).with_suffix(".funscript")


def funscript_of(video_path, *, output_dir) -> Path | None:
    """The script this video HAS -- the folder first, then the old place beside
    it -- or ``None`` when it has none."""
    dest = funscript_path_for(video_path, output_dir=output_dir)
    if dest.is_file():
        return dest
    beside = legacy_funscript_path_for(video_path)
    return beside if beside.is_file() else None


def synthesize_actions(duration_s: float, *, hz: float, loop: bool) -> list[dict]:
    """A periodic stroke over ``duration_s`` at ``hz`` full cycles per second.

    Emits alternating bottom/top extremes (``0``/``100``) every half-period; the
    device interpolates between them, so a plain point every half-stroke reads as a
    steady stroke. When ``loop`` is set, the half-period is stretched to fit a whole
    (even) number of halves into the clip, so the last action lands back at the start
    position at exactly ``duration`` — the script tiles seamlessly as the clip repeats.
    """
    duration_ms = int(round(duration_s * 1000))
    if duration_ms <= 0 or hz <= 0:
        return []
    half_period = 500.0 / hz  # ms between successive extremes (two per full cycle)
    if loop:
        halves = max(2, round(duration_ms / half_period))
        if halves % 2:  # keep it even so the final extreme matches the first (bottom)
            halves += 1
        half_period = duration_ms / halves
        count = halves + 1  # inclusive of both endpoints [0, duration]
    else:
        count = int(duration_ms // half_period) + 1
    return [
        {"at": int(round(i * half_period)), "pos": 0 if i % 2 == 0 else 100}
        for i in range(count)
    ]


def write_funscript(path, actions: list[dict]) -> None:
    """Write ``actions`` as a minimal funscript JSON document.

    Makes the folder it writes into: the scripts' folder is one this app owns
    and a user tidying the output dir can leave it out, so every writer would
    otherwise need the same guard.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": "1.0", "inverted": False, "range": 100, "actions": actions}),
        encoding="utf-8",
    )


# Anchor colors for the classic funscript-heatmap feel (mirrors sibling Nau's
# palette): idle bins read near-black, then blue -> cyan -> green -> yellow -> red
# as the average stroke speed (position units per second) climbs to 500.
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
    the average stroke speed in that bucket — the funscript heatmap the strip paints.

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


def read_actions(path) -> list[dict] | None:
    """The ``actions`` list from a funscript file, or ``None`` if absent/unreadable.

    ``None`` in is ``None`` out, so whatever :func:`funscript_of` answered can be
    handed straight here without a caller checking first.
    """
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    actions = data.get("actions") if isinstance(data, dict) else None
    return actions if isinstance(actions, list) else None


def video_duration_seconds(video_path) -> float | None:
    """Read a video's duration via OpenCV (frame count / fps), or ``None``.

    OpenCV is already a dependency (see ``thumbnail.py``) and reads the container
    header without spawning a console process, so it costs nothing at import time
    when kept lazy here.
    """
    import cv2  # heavy; imported lazily so the pure helpers don't pull it in

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


def ensure_funscript(video_path, *, loop: bool, hz: float, output_dir,
                     duration_provider=video_duration_seconds) -> Path | None:
    """Write ``video_path``'s script into the scripts folder if it has none.

    Idempotent: a script it already has is left untouched (and not even probed),
    wherever that is -- including the old place beside the clip, which is what
    keeps this from writing a second copy of every script predating the folder.
    Best-effort — a video whose duration can't be read is skipped with a log line
    rather than raising, so it never strands a completing generation.
    """
    video_path = Path(video_path)
    existing = funscript_of(video_path, output_dir=output_dir)
    if existing is not None:
        return existing
    dest = funscript_path_for(video_path, output_dir=output_dir)
    duration = duration_provider(video_path)
    if not duration or duration <= 0:
        logger.warning("No readable duration for %s; skipping funscript", video_path)
        return None
    actions = synthesize_actions(duration, hz=hz, loop=loop)
    if not actions:
        return None
    write_funscript(dest, actions)
    return dest
