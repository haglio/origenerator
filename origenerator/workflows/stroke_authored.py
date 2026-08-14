"""The shared machinery of stroke-authored video workflows.

A stroke-authored workflow flips motion authorship: the stroke is written down
first — turnaround points with a seeded human wobble, eased through every
half-stroke — and everything else derives from that one plan: the motion
conditioning the video model obeys, and the funscript the completion path
writes beside the finished clip. Two workflows share this base: the WAN 2.1
ATI one (the plan becomes a point track) and the WAN 2.2 Fun-Control one (the
plan becomes a rendered control video). Both also share the aim machinery —
coordinates authored in one fixed reference frame, auto-aimed at the detected
anchor when left untouched, rescaled into the output size derived from the
input image.
"""

import math
import random

from origenerator.workflows.base import WorkflowTemplate
from origenerator.workflows.derived_size import (
    measure_derived_size, override_size, resolve_input_image_path,
)
from origenerator.workflows.stroke_aim import detect_grip_aim

# The plan's fixed timeline: 121 points sampled at 24fps (5.0s of "plan time"),
# stretched over the clip's real duration by whichever conditioning consumes it
# — so a clip's effective cadence is the authored one scaled by (5.0 / clip
# seconds). The funscript applies the same mapping, which is what keeps script
# and pixels locked.
TRACK_POINTS = 121
TRACK_SECONDS = 5.0

# The reference frame the stored stroke coordinates are authored in. They're
# rescaled from here into the derived output space (see
# :meth:`StrokeAuthoredWorkflow._scaled_stroke_params`), and this doubles as
# the fallback size when the input image can't be measured.
REFERENCE_WIDTH = 480
REFERENCE_HEIGHT = 864


class StrokeAuthoredWorkflow(WorkflowTemplate):
    """Base for workflows whose motion follows a written-down stroke plan."""

    # The aim params auto-detection may fill; leaving ALL of them untouched is
    # what opts a run into detection, and editing ANY is the manual override.
    _AIM_KEYS = ("stroke_x", "stroke_top", "stroke_bottom", "anchor_x", "anchor_y")

    def _auto_aim_params(self, params: dict) -> dict:
        """``params`` with the stroke aimed at the detected anchor, when the user
        left every aim coordinate at its default and the start frame yields a
        detection — choosing where in the frame a thing is shouldn't be the
        user's job. Any edited coordinate, or no detection, leaves the given
        numbers exactly as they are. Fractions from the detector land in the
        reference frame, where all aim coordinates live."""
        defaults = self.default_params()
        if any(params[k] != defaults[k] for k in self._AIM_KEYS):
            return params
        aim = detect_grip_aim(resolve_input_image_path(params.get("input_image")))
        if aim is None:
            return params
        return {
            **params,
            "stroke_x": round(aim["stroke_x"] * REFERENCE_WIDTH),
            "anchor_x": round(aim["anchor_x"] * REFERENCE_WIDTH),
            "stroke_top": round(aim["stroke_top"] * REFERENCE_HEIGHT),
            "stroke_bottom": round(aim["stroke_bottom"] * REFERENCE_HEIGHT),
            "anchor_y": round(aim["anchor_y"] * REFERENCE_HEIGHT),
        }

    @staticmethod
    def _stroke_reversals(params: dict) -> list[tuple[float, float]]:
        """The authored stroke's turnaround points as ``(plan_t, y)`` pairs.

        Alternating half-strokes with a seeded wobble in each one's pace (±18%)
        and landing depth (up to 18% short), so the rhythm reads human rather
        than metronomic. Seeded by the generation seed: deterministic per run,
        re-rolled by a variation. These reversals are the single source both
        the motion conditioning and the funscript are built from, which is
        what keeps them locked."""
        rng = random.Random(params["seed"])
        top = float(params["stroke_top"])
        bottom = float(params["stroke_bottom"])
        depth = bottom - top
        half = 0.5 / params["stroke_hz"]
        reversals = [(0.0, top)]
        t, going_down = 0.0, True
        while t <= TRACK_SECONDS:
            t += half * rng.uniform(0.82, 1.18)
            short = depth * rng.uniform(0.0, 0.18)
            reversals.append((t, bottom - short if going_down else top + short))
            going_down = not going_down
        return reversals

    @classmethod
    def _stroke_series(cls, params: dict) -> list[float]:
        """The stroke as its 121 plan-time samples (y per sample): the
        reversals of :meth:`_stroke_reversals` with cosine easing through every
        half-stroke, so the hand decelerates into each turnaround instead of
        bouncing off it."""
        reversals = cls._stroke_reversals(params)
        ys, seg = [], 0
        for f in range(TRACK_POINTS):
            tt = f / 24.0
            while reversals[seg + 1][0] < tt:
                seg += 1
            (t0, y0), (t1, y1) = reversals[seg], reversals[seg + 1]
            eased = (1 - math.cos(math.pi * (tt - t0) / (t1 - t0))) / 2
            ys.append(y0 + (y1 - y0) * eased)
        return ys

    def _output_size(self, params: dict) -> tuple[int, int]:
        """The size this run renders at: the user's explicit width/height when the
        derived size was unlocked and overridden, else the size derived from the
        input image (:meth:`_derived_size`). The stroke plan is then rescaled into
        whichever size wins, so it stays in the same relative place either way."""
        return override_size(params) or self._derived_size(params)

    def _derived_size(self, params: dict) -> tuple[int, int]:
        """The output size derived from the input image: measured and scaled to
        the shared pixel budget (:func:`~origenerator.workflows.derived_size.
        measure_derived_size`), or the reference size when the image is missing or
        unreadable — so payload build never crashes on a stale or hand-typed
        filename, it just uses the default. Unlike the WAN 2.2 i2v pair these
        workflows can't defer sizing to the graph: the plan's pixel coordinates
        must be built app-side."""
        return measure_derived_size(params.get("input_image", "")) or (
            REFERENCE_WIDTH,
            REFERENCE_HEIGHT,
        )

    @staticmethod
    def _scaled_stroke_params(params: dict, width: int, height: int) -> dict:
        """``params`` with the stroke coordinates rescaled from the reference
        frame into the derived ``width``×``height`` space, so a stroke authored
        once lands in the same relative place whatever the input image's aspect
        ratio. X coordinates scale by the width ratio, Y by the height ratio;
        everything else (the rate, the seeds, …) passes through."""
        sx = width / REFERENCE_WIDTH
        sy = height / REFERENCE_HEIGHT
        return {
            **params,
            "stroke_x": params["stroke_x"] * sx,
            "anchor_x": params["anchor_x"] * sx,
            "stroke_top": params["stroke_top"] * sy,
            "stroke_bottom": params["stroke_bottom"] * sy,
            "anchor_y": params["anchor_y"] * sy,
        }

    # A funscript action must sit well clear of the OSR2 driver's 50ms poll: the
    # driver re-sends "next action, time until it" every poll, so actions spaced
    # near (or under) the poll period become a new target per tick and the device
    # spasms instead of gliding. Reversals plus at most one shaping point per
    # half-stroke keeps every gap far above this floor at any sane cadence.
    _MIN_HALF_STROKE_MS_FOR_SHAPING = 300

    def authored_actions(self, params: dict) -> list[dict]:
        """The funscript for the authored stroke: its reversal points — the
        same ones the motion conditioning is built from — mapped from plan time
        onto the clip's real duration and normalized to stroke depth (100 at the
        top of the stroke, 0 at the bottom). SPARSE by contract: the OSR2 driver
        interpolates between actions itself, and dense scripts make it jitter
        (see ``_MIN_HALF_STROKE_MS_FOR_SHAPING``). Each half-stroke long enough
        to afford it gets one mid point at 55% time / 82% travel, approximating
        the plan's cosine easing so the device also decelerates into the
        reversal rather than moving at one flat speed."""
        top = float(params["stroke_top"])
        bottom = float(params["stroke_bottom"])
        depth = (bottom - top) or 1.0
        video_s = params["frame_count"] / params["frame_rate"]
        scale = video_s / TRACK_SECONDS

        def to_ms(plan_t: float) -> int:
            return round(plan_t * scale * 1000)

        def to_pos(y: float) -> int:
            return max(0, min(100, round(100 * (bottom - y) / depth)))

        reversals = self._stroke_reversals(params)
        limit_ms = round(video_s * 1000)
        actions = [{"at": to_ms(reversals[0][0]), "pos": to_pos(reversals[0][1])}]
        for (t0, y0), (t1, y1) in zip(reversals, reversals[1:]):
            if to_ms(t1) - to_ms(t0) >= self._MIN_HALF_STROKE_MS_FOR_SHAPING:
                actions.append({
                    "at": to_ms(t0 + 0.55 * (t1 - t0)),
                    "pos": to_pos(y0 + 0.82 * (y1 - y0)),
                })
            actions.append({"at": to_ms(t1), "pos": to_pos(y1)})
        return [a for a in actions if a["at"] <= limit_ms]
