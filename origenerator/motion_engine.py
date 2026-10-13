"""The motion this app drives the OSR2 with — genau's wave, and what rides it.

The slideshow shows images, and an image gives the device nothing to follow, so
this supplies the motion instead. The waveform itself is not written here: the
shapes, the Speed bar's exponential map and the amplitude and center arithmetic
are :mod:`funestra.robot_hand` — the Robot Hand, genau's own, shared so both
apps move the same way rather than two ways that look alike until they don't.

What genau keeps elsewhere and this has to carry is the phase. Genau's engine
advances it against the clip's beats; here there is no clip, so the motion
free-runs on the driver's clock and the phase rides along with the bars, in
:class:`Motion`.

:mod:`funestra.learned_motion` is the one takeover: phrases of real scripting in
place of the waveform, played inside the bars' range and at the Speed bar's
pace; the rest of the time the motion is the single hand-driven wave.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from funestra import learned_motion
from funestra.learned_motion import LearnedMotionState, load_default_model
from funestra.robot_hand import (
    MAX_SPEED,
    MAX_TICK_SECONDS,
    MIN_SPEED,
    RobotHandState,
    WaveformShape,
    adjust_amplitude,
    adjust_center,
    adjust_speed,
    bpm_for_speed,
    cycle_shape,
    phase_advanced,
    position_fraction,
    set_amplitude,
    set_center,
    set_max_intensity,
    set_speed,
)
from funestra.robot_hand import trace_window as wave_trace_window

__all__ = [
    "MAX_SPEED",
    "MIN_SPEED",
    "Motion",
    "RobotHandState",
    "WaveformShape",
    "adjust_amplitude",
    "adjust_center",
    "adjust_speed",
    "advance",
    "bpm_for_speed",
    "cycle_shape",
    "disable_learned_motion",
    "enable_learned_motion",
    "position",
    "position_ahead",
    "quarter_offset",
    "set_amplitude",
    "set_center",
    "set_max_intensity",
    "set_speed",
    "tick_learned_motion",
    "toggle_learned_motion",
    "trace_window",
]


@dataclass
class Motion:
    """The live motion: genau's bars, the learned motion, and the phase."""

    state: RobotHandState = field(default_factory=RobotHandState)
    # Its model is read from the package the first time it is switched on.
    learned: LearnedMotionState = field(default_factory=LearnedMotionState)
    phase: float = 0.0
    # The phase counted up without wrapping: what the readout's knots are
    # anchored to, so they stay put from one cycle to the next.
    phase_total: float = 0.0

    @property
    def bpm(self) -> float:
        return self.state.bpm


def advance(motion: Motion, dt_s: float) -> None:
    """Carry the wave's phase forward by ``dt_s`` seconds of motion."""
    motion.phase = phase_advanced(motion.phase, motion.state.bpm, dt_s)
    motion.phase_total += max(0.0, min(dt_s, MAX_TICK_SECONDS)) * motion.state.bpm / 60.0


def tick_learned_motion(motion: Motion, now: float) -> None:
    """Let the phrases carry the motion, if the learned motion has it.  The
    first phrase begins where the wave already has the device, so the takeover
    cannot be felt."""
    learned_motion.tick_learned_motion(
        motion.state, motion.learned, now, start_fraction=_envelope_fraction(motion))


def toggle_learned_motion(motion: Motion) -> None:
    """Hands off to the scripts, or back — genau's ``;``."""
    if motion.learned.active:
        disable_learned_motion(motion)
    else:
        enable_learned_motion(motion)


def enable_learned_motion(motion: Motion) -> None:
    """Hands off to the scripts, whichever way the switch was standing."""
    if motion.learned.model is None:
        motion.learned.model = load_default_model()
    learned_motion.enable_learned_motion(motion.learned)


def disable_learned_motion(motion: Motion) -> None:
    learned_motion.disable_learned_motion(motion.learned)


def quarter_offset(motion: Motion) -> None:
    """Jump a quarter cycle — genau's ``\\`` key, for when the motion is out of
    step with what is on screen and you want it moved rather than restarted."""
    motion.phase = (motion.phase + 0.25) % 1.0
    motion.phase_total += 0.25


def position(motion: Motion) -> float:
    """Where the motion is now, 0-100 — the scale
    :func:`origenerator.osr2.format_position` takes."""
    if motion.learned.active:
        return learned_motion.position(motion.learned, motion.state)
    return _at(motion, motion.phase)


def _envelope_fraction(motion: Motion) -> float:
    """How far up the bars' envelope the wave has the device, 0 at its floor
    and 1 at its ceiling — where the learned motion's first phrase begins."""
    state = motion.state
    if state.amplitude <= 0:
        return 0.0
    low = max(0.0, state.center - state.amplitude / 2)
    span = min(100.0, state.center + state.amplitude / 2) - low
    return (_at(motion, motion.phase) - low) / span if span > 0 else 0.0


def position_ahead(motion: Motion, lead_s: float) -> float:
    """Where the motion will be ``lead_s`` seconds from now, 0-100.

    This, not :func:`position`, is what a device command should aim at: the OSR2
    is told a place and how long to take getting there, so the place has to be
    one it is actually due to be at when the time is up. Aimed at the present it
    can only ever chase.
    """
    if motion.learned.active:
        return learned_motion.position(motion.learned, motion.state, lead_s)
    return _at(motion, motion.phase + lead_s * motion.state.bpm / 60.0)


def trace_window(motion: Motion, samples: int, span_s: float) -> tuple[list[float], float]:
    """The motion sampled forward from now as 0-1 heights — the drive readout's
    picture of the motion the device is being sent, ``span_s`` seconds of it —
    as ``samples`` + 1 values, the last one the knot past the readout's edge,
    and how far the drawn line is shifted left, as a fraction of one sample.

    Both sources are read on knots a fixed stretch of their own clock apart --
    the wave on its phase, the learned motion on its script -- so the picture
    holds still between knots and slides by the fraction rather than being
    redrawn at fixed columns.
    """
    if motion.learned.active:
        return learned_motion.trace_window(motion.learned, motion.state, samples, span_s)
    state = motion.state
    return wave_trace_window(
        state.shape, state.amplitude, state.center, phase=motion.phase_total,
        bpm=state.bpm, samples=samples, span_s=span_s)


def _at(motion: Motion, phase: float) -> float:
    state = motion.state
    return 100.0 * position_fraction(
        phase, shape=state.shape, amplitude=state.amplitude, center=state.center)
