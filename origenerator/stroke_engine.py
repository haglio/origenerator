"""A self-generated stroke for the OSR2 — motion with no funscript behind it.

The auto-generate slideshow shows images, and an image gives the device nothing
to follow — so this supplies the motion instead: genau's direct-control model (a
waveform shaped by speed, amplitude, and center), with none of genau's clip
visuals. Pure math, Qt-free and device-free: the state advances a phase and
samples a 0-100 stroke position from it, and
:mod:`origenerator.gui.osr2_stroke_driver` owns the clock and the wire.
"""

import math
from dataclasses import dataclass
from enum import Enum


class StrokeShape(Enum):
    SINE = "sine"
    TRIANGLE = "triangle"
    ROUNDED_SQUARE = "square"
    SAWTOOTH = "sawtooth"


# Speed is the user-facing knob (a step feels the same anywhere on the dial);
# BPM — strokes per minute — is what the phase actually advances by, mapped
# exponentially so the slow end gets as much resolution as the fast end.
MIN_SPEED, MAX_SPEED = 5, 100
MIN_BPM, MAX_BPM = 5.0, 200.0

# A stalled clock (the app blocked, the timer starved) must not slingshot the
# device: a tick never advances the phase by more than this much wall time.
_MAX_TICK_S = 0.1


def bpm_for_speed(speed: int) -> float:
    t = (speed - MIN_SPEED) / (MAX_SPEED - MIN_SPEED)
    return MIN_BPM * (MAX_BPM / MIN_BPM) ** t


@dataclass
class StrokeState:
    """The stroke being traced: how fast (``speed`` → strokes/minute), how far
    (``amplitude``, % of the axis), around where (``intended_center``, pulled in
    as needed so the sweep stays on the axis), its ``shape``, and how far through
    the current cycle it is (``phase``, 0..1)."""

    speed: int = 50
    amplitude: int = 100
    intended_center: int = 50
    shape: StrokeShape = StrokeShape.SINE
    phase: float = 0.0

    @property
    def bpm(self) -> float:
        return bpm_for_speed(self.speed)

    @property
    def center(self) -> int:
        """The effective center: what was asked for, clamped so the amplitude fits."""
        half = self.amplitude // 2
        return max(half, min(100 - half, self.intended_center))


def set_speed(state: StrokeState, value: int) -> None:
    state.speed = max(MIN_SPEED, min(MAX_SPEED, value))


def adjust_speed(state: StrokeState, delta: int) -> None:
    set_speed(state, state.speed + delta)


def set_amplitude(state: StrokeState, value: int) -> None:
    state.amplitude = max(0, min(100, value))


def adjust_amplitude(state: StrokeState, delta: int) -> None:
    set_amplitude(state, state.amplitude + delta)


def set_center(state: StrokeState, value: int) -> None:
    """Aim the center at ``value``; the effective center still clamps so the
    amplitude fits (see :attr:`StrokeState.center`)."""
    state.intended_center = max(0, min(100, value))


def adjust_center(state: StrokeState, delta: int) -> None:
    """Nudge the intended center, stopping at the edge the amplitude allows.

    A step that would overshoot the reachable range lands on its limit; once at
    (or beyond) that limit, further pushes in the same direction do nothing —
    the intent doesn't creep off past what the device can express.
    """
    half = state.amplitude // 2
    lo, hi = half, 100 - half
    new = state.intended_center + delta
    if new < lo:
        if state.intended_center <= lo:
            return
        new = lo
    elif new > hi:
        if state.intended_center >= hi:
            return
        new = hi
    state.intended_center = max(0, min(100, new))


def cycle_shape(state: StrokeState, step: int = 1) -> None:
    shapes = list(StrokeShape)
    state.shape = shapes[(shapes.index(state.shape) + step) % len(shapes)]


def advance(state: StrokeState, dt_s: float) -> None:
    """Advance the phase by ``dt_s`` seconds of stroking at the current speed."""
    dt = max(0.0, min(dt_s, _MAX_TICK_S))
    state.phase = (state.phase + dt * state.bpm / 60.0) % 1.0


def _waveform_raw(phase: float, shape: StrokeShape) -> float:
    """One full round trip per cycle, normalized 0 (bottom) to 1 (top)."""
    frac = phase % 1.0
    if shape is StrokeShape.TRIANGLE:
        return 1 - abs(2 * frac - 1)
    if shape is StrokeShape.ROUNDED_SQUARE:
        k = 3.0  # how hard the wave slams between its dwell ends
        return (1 - math.tanh(k * math.cos(2 * math.pi * frac)) / math.tanh(k)) / 2
    if shape is StrokeShape.SAWTOOTH:
        rise = 0.3  # quick up, long draw back down
        return frac / rise if frac < rise else 1 - (frac - rise) / (1 - rise)
    return (1 - math.cos(2 * math.pi * frac)) / 2  # sine


def position(state: StrokeState) -> float:
    """The stroke position for the current phase, 0-100 (bottom-top) — the same
    scale :func:`origenerator.osr2.format_position` takes."""
    return _position_at(state, state.phase)


def _position_at(state: StrokeState, phase: float) -> float:
    raw = _waveform_raw(phase, state.shape)
    half = state.amplitude / 2
    low = max(0.0, state.center - half)
    high = min(100.0, state.center + half)
    return low + raw * (high - low)


def trace(state: StrokeState, samples: int, span_s: float) -> list[float]:
    """The stroke sampled forward from now, as 0-1 heights — the drive HUD's
    picture of the motion the device is being sent, ``span_s`` seconds of it."""
    span_cycles = span_s * state.bpm / 60.0
    return [
        _position_at(state, state.phase + (i / max(1, samples - 1)) * span_cycles) / 100.0
        for i in range(samples)
    ]
