"""Synthesize and read the funscript that rides alongside a generated video.

A ``.funscript`` is a JSON file of ``{"at": <ms>, "pos": 0..100}`` actions describing
stroke motion for a haptic device (the OSR2). Origenerator's videos carry no explicit
motion track — the diffusion model's motion lives only in the pixels — so rather than
measuring the finished video, this authors a stroke *with* it from what the generation
already knows: the clip's duration, and whether it loops. The result is a rhythm, not a
pixel-accurate script; the whole generator is one function so a later swap to a
measured (FunGen) or authored (ATI) source touches nothing else.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def funscript_path_for(video_path) -> Path:
    """The sidecar path for a video: same stem, ``.funscript`` extension."""
    return Path(video_path).with_suffix(".funscript")


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
    """Write ``actions`` as a minimal funscript JSON document."""
    Path(path).write_text(
        json.dumps({"version": "1.0", "inverted": False, "range": 100, "actions": actions}),
        encoding="utf-8",
    )


def read_actions(path) -> list[dict] | None:
    """The ``actions`` list from a funscript file, or ``None`` if absent/unreadable."""
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


def ensure_funscript(video_path, *, loop: bool, hz: float,
                     duration_provider=video_duration_seconds) -> Path | None:
    """Write the sidecar for ``video_path`` if it doesn't already have one.

    Idempotent: an existing ``.funscript`` is left untouched (and not even probed),
    so this is safe to call after every generation and to sweep across old videos.
    Best-effort — a video whose duration can't be read is skipped with a log line
    rather than raising, so it never strands a completing generation.
    """
    video_path = Path(video_path)
    dest = funscript_path_for(video_path)
    if dest.exists():
        return dest
    duration = duration_provider(video_path)
    if not duration or duration <= 0:
        logger.warning("No readable duration for %s; skipping funscript", video_path)
        return None
    actions = synthesize_actions(duration, hz=hz, loop=loop)
    if not actions:
        return None
    write_funscript(dest, actions)
    return dest
