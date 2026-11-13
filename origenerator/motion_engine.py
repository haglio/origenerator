from __future__ import annotations

from dataclasses import dataclass, field

from funestra import learned_motion
from funestra.hand_motion import HandMotion, ways_the_hand_moves
from funestra.learned_motion import LearnedMotionState, load_default_model
from funestra.robot_hand import (
    MAX_SPEED,
    MAX_TICK_SECONDS,
    MIN_SPEED,
    RobotHandState,
    TraceSpan,
    Waveform,
    WaveformShape,
    adjust_amplitude,
    adjust_center,
    adjust_speed,
    bpm_for_speed,
    cycle_shape,
    phase_advanced,
    set_amplitude,
    set_bars,
    set_center,
    set_max_intensity,
    set_speed,
)

_SHAPES_BY_NAME = {shape.value: shape for shape in WaveformShape}

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
    "set_amplitude",
    "set_center",
    "set_max_intensity",
    "set_speed",
    "settings_of",
    "take_settings",
    "tick_learned_motion",
    "toggle_learned_motion",
    "trace_window",
]


@dataclass
class Motion:
    state: RobotHandState = field(default_factory=RobotHandState)
    learned: LearnedMotionState = field(default_factory=LearnedMotionState)
    phase: float = 0.0
    phase_total: float = 0.0

    @property
    def bpm(self) -> float:
        return self.state.bpm

    @property
    def hand(self) -> HandMotion:
        return HandMotion(self.state, ways_the_hand_moves(self.learned))


def advance(motion: Motion, dt_s: float) -> None:
    motion.phase = phase_advanced(motion.phase, motion.state.bpm, dt_s)
    motion.phase_total += max(0.0, min(dt_s, MAX_TICK_SECONDS)) * motion.state.bpm / 60.0


def tick_learned_motion(motion: Motion, now: float) -> None:
    motion.hand.tick(now, start_fraction=_envelope_fraction(motion))


def toggle_learned_motion(motion: Motion) -> None:
    if motion.learned.active:
        disable_learned_motion(motion)
    else:
        enable_learned_motion(motion)


def enable_learned_motion(motion: Motion) -> None:
    if motion.learned.model is None:
        motion.learned.model = load_default_model()
    learned_motion.enable_learned_motion(motion.learned)


def disable_learned_motion(motion: Motion) -> None:
    learned_motion.disable_learned_motion(motion.learned)


def settings_of(motion: Motion) -> dict:
    bars = motion.state
    return {"speed": bars.speed, "amplitude": bars.amplitude, "center": bars.intended_center,
            "shape": bars.shape.value, "human_inspired": motion.learned.active}


def take_settings(motion: Motion, saved) -> None:
    if not isinstance(saved, dict):
        return
    speed, amplitude, center = (saved.get(name) for name in ("speed", "amplitude", "center"))
    if all(type(number) is int for number in (speed, amplitude, center)):
        set_bars(motion.state, speed=speed, amplitude=amplitude, center=center)
    if saved.get("shape") in _SHAPES_BY_NAME:
        motion.state.shape = _SHAPES_BY_NAME[saved["shape"]]
    if saved.get("human_inspired") is True:
        enable_learned_motion(motion)


def position(motion: Motion) -> float:
    return motion.hand.height(motion.phase)


def _envelope_fraction(motion: Motion) -> float:
    state = motion.state
    if state.amplitude <= 0:
        return 0.0
    low = max(0.0, state.center - state.amplitude / 2)
    span = min(100.0, state.center + state.amplitude / 2) - low
    return (_at(motion, motion.phase) - low) / span if span > 0 else 0.0


def position_ahead(motion: Motion, lead_s: float) -> float:
    # The OSR2 is told a place and how long to take getting there; aimed at the present it only chases.
    return motion.hand.height(motion.phase, lead_s=lead_s)


def trace_window(motion: Motion, samples: int, span_s: float) -> tuple[list[float], float]:
    return motion.hand.trace(TraceSpan(motion.phase_total, motion.state.bpm, samples, span_s))


def _at(motion: Motion, phase: float) -> float:
    return 100.0 * Waveform.of(motion.state).height_at(phase)
