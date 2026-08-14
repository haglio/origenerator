"""Render a stroke plan as the control video Fun-Control conditions on.

The WAN 2.2 Fun-Control models take their motion instruction as a video: what
moves in the control clip is what moves in the generation. Trialing this on
real content settled three rules the rendering below encodes. Only movement
binds — a stationary marker is ignored outright, so even the steadying hand
gets a small synchronized sway rather than a fixed point. Markers must start
apart, each on the body part it commands — two markers crowding one part left
the other part unclaimed and improvising. And once bound, a part follows its
marker's path faithfully, so the primary marker rides the exact stroke series
the funscript is written from.

The rendered file is content-addressed under ComfyUI's input tree: the same
plan, aim, and size always name the same file, so re-rolls and re-queues reuse
it instead of re-encoding, and distinct runs never collide.
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from origenerator.config import COMFYUI_INPUT_DIR

# Console-window suppression for the ffmpeg encode (see importer.py: Windows
# flashes a console per console-tool subprocess without it; a no-op elsewhere).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_DOT_RADIUS = 14
# The primary marker (the stroking hand) is white; the secondary (the
# steadying hand at the base) is green — distinct so the model can't read the
# pair as one large object.
_PRIMARY_COLOR = (255, 255, 255)
_SECONDARY_COLOR = (0, 220, 0)
# How much of the stroke's travel the base hand echoes: enough motion to bind,
# small enough to read as a hand holding steady.
_SWAY_FACTOR = 0.15

# Where the rendered control videos live, inside ComfyUI's input tree so the
# server can read them wherever it runs from.
_CONTROL_SUBDIR = "stroke_control"


def control_marker_positions(
    series: list[float], stroke_x: float, stroke_top: float,
    anchor_x: float, anchor_y: float, frame_count: int,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Per output frame, the ``(primary_xy, secondary_xy)`` marker centers.

    The plan's fixed-timeline series is resampled onto ``frame_count`` frames;
    the primary marker rides it at the stroke column, and the secondary sways
    at the anchor by :data:`_SWAY_FACTOR` of the primary's travel from the
    stroke top — synchronized, so the pair reads as two hands in one rhythm.
    """
    last = len(series) - 1
    positions = []
    for f in range(frame_count):
        t_frac = f / (frame_count - 1) if frame_count > 1 else 0.0
        y = series[min(last, round(t_frac * last))]
        positions.append((
            (stroke_x, y),
            (anchor_x, anchor_y + (y - stroke_top) * _SWAY_FACTOR),
        ))
    return positions


def render_control_video(
    positions: list[tuple[tuple[float, float], tuple[float, float]]],
    width: int, height: int, frame_rate: float,
) -> Path:
    """Render marker frames to an H.264 file under ComfyUI's input tree and
    return its path. Content-addressed and idempotent: identical inputs name an
    existing file, which is returned without re-encoding."""
    key = hashlib.sha1(
        json.dumps([positions, width, height, frame_rate], default=str).encode()
    ).hexdigest()[:16]
    dest_dir = COMFYUI_INPUT_DIR / _CONTROL_SUBDIR
    dest = dest_dir / f"stroke_{key}.mp4"
    if dest.is_file():
        return dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for f, (primary, secondary) in enumerate(positions):
            img = Image.new("RGB", (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            for (cx, cy), color in ((primary, _PRIMARY_COLOR), (secondary, _SECONDARY_COLOR)):
                draw.ellipse(
                    [cx - _DOT_RADIUS, cy - _DOT_RADIUS, cx + _DOT_RADIUS, cy + _DOT_RADIUS],
                    fill=color,
                )
            img.save(Path(tmp) / f"f{f:04d}.png")
        _encode(Path(tmp) / "f%04d.png", frame_rate, dest)
    return dest


def _encode(frame_pattern: Path, frame_rate: float, dest: Path) -> None:
    """The ffmpeg encode, isolated so tests can fake it. Writes via a partial
    name and renames, so a killed encode never leaves a plausible-looking file
    for the idempotence check to trust."""
    partial = dest.with_suffix(".partial.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-framerate", str(frame_rate),
         "-i", str(frame_pattern), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "12", str(partial)],
        check=True, creationflags=_NO_WINDOW,
    )
    partial.replace(dest)
