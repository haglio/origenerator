"""The authored motion an ATI run is conditioned on, and the funscript of it.

ATI is the one workflow whose motion is not left to the diffusion model: a
track of pixel coordinates is authored here and handed to ``WanTrackToVideo``,
which is why the clip and its haptic script can be locked to each other. Both
are built from one sequence of turnarounds (:func:`motion_reversals`) — the
pixel track eases between them, the funscript reports them — so the device is
never describing a motion the pixels do not make.

Apart from the graph the workflow module assembles: the two things this
computes are a motion and a script for it, neither of which mentions a node.
"""
from __future__ import annotations

import json
import math
import random

from origenerator.workflows.frame_rate import NATIVE_FPS

# ATI's track convention is fixed regardless of the clip: 121 points sampled at
# 24fps (5.0s of "track time"), which ComfyUI's WanTrackToVideo resamples onto
# the actual frame count — so a clip's effective cadence is the authored one
# scaled by (5.0 / clip seconds). Both the tracks and the funscript below use
# the same mapping, which is what keeps them locked to each other.
TRACK_POINTS = 121
TRACK_SECONDS = 5.0
# The three cluster points ride the motion slightly staggered (as derisked in
# the PoC): enough spread to read as a hand, not so much it smears the patch.
_CLUSTER_OFFSETS = ((-5.0, -30.0), (3.0, 0.0), (-3.0, 30.0))

# The reference frame the stored motion coordinates are authored in. They're
# rescaled from here into the derived output space (see
# :func:`scaled_motion_params`), and this doubles as the fallback size when the
# input image can't be measured.
REFERENCE_WIDTH = 480
REFERENCE_HEIGHT = 864

# A funscript action must sit well clear of the OSR2 driver's 50ms poll: the
# driver re-sends "next action, time until it" every poll, so actions spaced
# near (or under) the poll period become a new target per tick and the device
# spasms instead of gliding. Reversals plus at most one shaping point per
# half-cycle keeps every gap far above this floor at any sane cadence.
_MIN_HALF_CYCLE_MS_FOR_SHAPING = 300


def motion_reversals(params: dict) -> list[tuple[float, float]]:
    """The authored motion's turnaround points as ``(track_t, y)`` pairs.

    Alternating half-cycles with a seeded wobble in each one's pace (±18%)
    and landing depth (up to 18% short), so the rhythm reads human rather
    than metronomic. Seeded by the generation seed: deterministic per run,
    re-rolled by a variation. These reversals are the single source both
    the pixel track and the funscript are built from, which is what keeps
    them locked."""
    rng = random.Random(params["seed"])
    top = float(params["motion_ceiling"])
    floor = float(params["motion_floor"])
    depth = floor - top
    half = 0.5 / params["motion_hz"]
    reversals = [(0.0, top)]
    t, going_down = 0.0, True
    while t <= TRACK_SECONDS:
        t += half * rng.uniform(0.82, 1.18)
        short = depth * rng.uniform(0.0, 0.18)
        reversals.append((t, floor - short if going_down else top + short))
        going_down = not going_down
    return reversals


def motion_series(params: dict) -> list[float]:
    """The motion as its 121 track-time samples (y per sample): the reversals
    of :func:`motion_reversals` with cosine easing through every half-cycle, so
    the hand decelerates into each turnaround instead of bouncing off it."""
    reversals = motion_reversals(params)
    ys, seg = [], 0
    for f in range(TRACK_POINTS):
        tt = f / 24.0
        while reversals[seg + 1][0] < tt:
            seg += 1
        (t0, y0), (t1, y1) = reversals[seg], reversals[seg + 1]
        eased = (1 - math.cos(math.pi * (tt - t0) / (t1 - t0))) / 2
        ys.append(y0 + (y1 - y0) * eased)
    return ys


def scaled_motion_params(params: dict, width: int, height: int) -> dict:
    """``params`` with the motion coordinates rescaled from the 480×864
    reference frame into the derived ``width``×``height`` space, so a track
    authored once lands in the same relative place whatever the input image's
    aspect ratio. X coordinates scale by the width ratio, Y by the height
    ratio; everything else (the rate, the seeds, …) passes through."""
    sx = width / REFERENCE_WIDTH
    sy = height / REFERENCE_HEIGHT
    return {
        **params,
        "motion_x": params["motion_x"] * sx,
        "anchor_x": params["anchor_x"] * sx,
        "motion_ceiling": params["motion_ceiling"] * sy,
        "motion_floor": params["motion_floor"] * sy,
        "anchor_y": params["anchor_y"] * sy,
    }


def motion_tracks(params: dict) -> str:
    """The tracks JSON: three staggered points riding the authored motion
    series, plus one static point pinning the anchor. 121 points at 24fps,
    ATI's fixed convention."""
    amplitude = (params["motion_floor"] - params["motion_ceiling"]) / 2
    series = motion_series(params)
    tracks = []
    for x_off, y_off in _CLUSTER_OFFSETS:
        spread = min(abs(y_off), amplitude * 0.4) * (1 if y_off >= 0 else -1)
        tracks.append([
            {"x": float(params["motion_x"] + x_off), "y": float(y + spread)}
            for y in series
        ])
    tracks.append(
        [{"x": float(params["anchor_x"]), "y": float(params["anchor_y"])}] * TRACK_POINTS
    )
    return json.dumps(tracks)


def authored_actions(params: dict) -> list[dict]:
    """The funscript for the authored motion: its reversal points — the
    same ones the pixel track is built from — mapped from track time onto
    the clip's real duration and normalized to travel depth (100 at the
    ceiling, 0 at the floor). SPARSE by contract: the OSR2 driver
    interpolates between actions itself, and dense scripts make it jitter
    (see :data:`_MIN_HALF_CYCLE_MS_FOR_SHAPING`). Each half-cycle long enough
    to afford it gets one mid point at 55% time / 82% travel, approximating
    the track's cosine easing so the device also decelerates into the
    reversal rather than moving at one flat speed."""
    top = float(params["motion_ceiling"])
    floor = float(params["motion_floor"])
    depth = (floor - top) or 1.0
    video_s = params["frame_count"] / NATIVE_FPS
    scale = video_s / TRACK_SECONDS

    def to_ms(track_t: float) -> int:
        return round(track_t * scale * 1000)

    def to_pos(y: float) -> int:
        return max(0, min(100, round(100 * (floor - y) / depth)))

    reversals = motion_reversals(params)
    limit_ms = round(video_s * 1000)
    actions = [{"at": to_ms(reversals[0][0]), "pos": to_pos(reversals[0][1])}]
    for (t0, y0), (t1, y1) in zip(reversals, reversals[1:]):
        if to_ms(t1) - to_ms(t0) >= _MIN_HALF_CYCLE_MS_FOR_SHAPING:
            actions.append({
                "at": to_ms(t0 + 0.55 * (t1 - t0)),
                "pos": to_pos(y0 + 0.82 * (y1 - y0)),
            })
        actions.append({"at": to_ms(t1), "pos": to_pos(y1)})
    return [a for a in actions if a["at"] <= limit_ms]
