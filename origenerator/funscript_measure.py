"""Measure a stroke track from a generated video's actual on-screen motion.

This is the measured source the synthetic metronome was always a placeholder for
(see :mod:`origenerator.funscript`): a CPU-only optical-flow tracker follows the
vertical motion in the middle of the frame and turns it into a 0-100 position
series, so the funscript corresponds to what the video *does* rather than to a
guessed rhythm. No GPU, no model — dense inverse-search optical flow (DIS) over
the frames, then a small amount of signal shaping.

The shaping matters as much as the tracking. Flow gives a per-frame *velocity*;
using it directly as the position is the bug this module exists to avoid, because
mid-stroke — where velocity is near-constant — a scaled velocity slams into the
0/100 clamp and the device snaps between extremes instead of gliding. Instead the
velocity is integrated into a displacement, its slow integration drift is removed,
and the result is scaled by *how much the clip actually moves*: a vigorous stroke
fills the full 0-100 range, a nearly-still clip stays near the middle rather than
amplifying its own noise into a phantom stroke.

The action list is kept SPARSE (a curve simplification, not one point per frame)
for the same reason ``wan21_ati_i2v`` keeps its authored script sparse: the OSR2
driver interpolates between actions and re-targets every 50 ms poll, so points
packed tighter than that make it spasm. Simplification keeps only the points
linear interpolation needs to retrace the measured curve within a tolerance.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# ROI: the central band where stroke motion lives, as fractions of the frame.
# Whole-frame averaging washes the stroke out, so we watch only the middle.
_ROI_Y = (0.15, 0.90)
_ROI_X = (0.25, 0.75)
_MAG_PERCENTILE = 85          # keep only the highest-motion vectors in the ROI
_WORK_WIDTH = 320             # downscale for speed; the signal is large-scale

# Peak-to-peak of the integrated displacement (in frame-height fractions) that a
# full 0-100 stroke corresponds to. Motion at or above this saturates to the full
# range; weaker motion scales down proportionally. Calibrated against 49 real
# clips: a vigorous, clearly-stroking clip integrates to ~0.10 of frame height,
# which is where the top ~20% saturate; the median clip (~0.04) reads as a gentle
# ~40%% stroke — see tests/test_funscript_measure.py.
_FULL_SCALE = 0.10
_DEAD_ZONE = 0.015            # below this p2p, the clip is treated as motionless

_SIMPLIFY_EPS = 6.0           # curve-fit tolerance in position units (0-100)
_MIN_GAP_MS = 120.0           # never emit two actions closer than this
_MIN_FRAMES = 8               # too few frames to read a stroke from


def _median3(a: np.ndarray) -> np.ndarray:
    """Length-preserving median-of-3 filter (edges use nearest, via edge-pad)."""
    if len(a) < 3:
        return a.astype(np.float64)
    p = np.pad(a.astype(np.float64), 1, mode="edge")
    return np.median(np.stack([p[:-2], p[1:-1], p[2:]]), axis=0)


def _box_reflect(a: np.ndarray, win: int) -> np.ndarray:
    """Centered moving average of width ``win`` with reflect padding — the slow
    trend we subtract to detrend the integrated displacement."""
    win = max(1, int(win))
    if win % 2 == 0:
        win += 1
    if win <= 1 or win >= len(a):
        return np.full(len(a), float(np.mean(a)))
    pad = win // 2
    padded = np.pad(a.astype(np.float64), pad, mode="reflect")
    kernel = np.ones(win) / win
    return np.convolve(padded, kernel, mode="valid")


def velocities_to_positions(dy: np.ndarray) -> np.ndarray:
    """Integrate per-frame vertical velocity into a 0-100 position series.

    ``dy`` is vertical flow per frame in frame-height fractions (up/down sign as
    OpenCV reports it). Returns one position per input sample. The output is
    centered near 50 and scaled by the clip's real motion, so amplitude is
    meaningful across clips rather than always stretched to the full range.
    """
    dy = np.asarray(dy, dtype=np.float64)
    n = len(dy)
    if n < 2:
        return np.full(max(n, 1), 50.0)
    v = _median3(dy)
    disp = np.cumsum(-v)  # downward flow (+vy) reads as descending toward 0
    # Detrend over ~1.5 stroke periods, estimated from the velocity's spectrum.
    vm = v - v.mean()
    spec = np.abs(np.fft.rfft(vm))
    spec[0] = 0.0
    peak = int(np.argmax(spec)) if spec.size > 1 else 0
    period = n / peak if peak > 0 else float(n)
    win = int(np.clip(1.5 * period, 15, max(15, n // 2)))
    base = disp - _box_reflect(disp, win)
    lo, hi = np.percentile(base, [2, 98])
    amplitude = hi - lo
    if amplitude < _DEAD_ZONE:
        return np.full(n, 50.0)
    gain = min(1.0, amplitude / _FULL_SCALE)
    pos = 50.0 + (base - np.median(base)) / amplitude * 100.0 * gain
    return np.clip(pos, 0.0, 100.0)


def _frame_velocities(video_path):
    """Per-frame median vertical flow in the ROI, plus the clip's fps.

    Returns ``(dy, fps)`` where ``dy`` is one velocity per frame transition in
    frame-height fractions, or ``(None, None)`` if the clip can't be read.
    """
    import cv2  # heavy; kept lazy so the pure shaping helpers don't pull it in

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        return None, None
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
    prev = None
    dys: list[float] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.shape[1] > _WORK_WIDTH:
            h = int(round(gray.shape[0] * _WORK_WIDTH / gray.shape[1]))
            gray = cv2.resize(gray, (_WORK_WIDTH, h))
        if prev is not None:
            flow = dis.calc(prev, gray, None)
            h, w = gray.shape
            y0, y1 = int(_ROI_Y[0] * h), int(_ROI_Y[1] * h)
            x0, x1 = int(_ROI_X[0] * w), int(_ROI_X[1] * w)
            roi = flow[y0:y1, x0:x1]
            mag = np.sqrt(roi[..., 0] ** 2 + roi[..., 1] ** 2)
            keep = mag >= np.percentile(mag, _MAG_PERCENTILE)
            vy = roi[..., 1][keep]
            dys.append(float(np.median(vy)) / h if vy.size else 0.0)
        prev = gray
    cap.release()
    if fps <= 0 or len(dys) < _MIN_FRAMES:
        return None, None
    return np.asarray(dys, dtype=np.float64), fps


def _simplify(times_ms: np.ndarray, pos: np.ndarray, eps: float,
              min_gap_ms: float) -> list[tuple[float, float]]:
    """Recursive curve simplification (Ramer-Peucker) with a minimum time gap.

    Keeps the fewest points whose linear interpolation stays within ``eps`` of the
    measured curve — turnarounds survive (they deviate most), flats collapse — then
    drops any point closer than ``min_gap_ms`` to the previous kept point so the
    device is never re-targeted faster than it can glide.
    """
    n = len(pos)
    if n == 0:
        return []
    if n == 1:
        return [(float(times_ms[0]), float(pos[0]))]
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        seg = pos[i:j + 1]
        t0, t1 = times_ms[i], times_ms[j]
        span = t1 - t0 or 1.0
        interp = pos[i] + (pos[j] - pos[i]) * (times_ms[i:j + 1] - t0) / span
        dev = np.abs(seg - interp)
        k = int(np.argmax(dev))
        if dev[k] > eps:
            keep[i + k] = True
            stack.append((i, i + k))
            stack.append((i + k, j))
    out: list[tuple[float, float]] = []
    for idx in np.flatnonzero(keep):
        t, p = float(times_ms[idx]), float(pos[idx])
        if out and t - out[-1][0] < min_gap_ms and idx != n - 1:
            continue
        out.append((t, p))
    return out


def measure_actions(video_path, *, velocities=_frame_velocities) -> list[dict]:
    """The measured funscript actions for ``video_path``.

    ``velocities`` is injectable so the shaping can be tested without decoding a
    real clip. Returns ``[]`` (rather than raising) for a clip too short or
    unreadable to measure, so a completing generation is never stranded.
    """
    dy, fps = velocities(video_path)
    if dy is None or fps is None or len(dy) < _MIN_FRAMES:
        return []
    pos = velocities_to_positions(dy)
    times = np.arange(len(pos)) * (1000.0 / fps)
    points = _simplify(times, pos, _SIMPLIFY_EPS, _MIN_GAP_MS)
    return [{"at": int(round(t)), "pos": int(round(np.clip(p, 0, 100)))}
            for t, p in points]
