"""The motion this app drives the OSR2 with — genau's wave, and what rides it.

The slideshow shows images, and an image gives the device nothing to follow, so
this supplies the motion instead. The waveform itself is not written here: the
shapes, the speed dial's exponential map and the amplitude and center arithmetic
are :mod:`player_core.robot_hand` — the Robot Hand, genau's own, shared so both
apps move the same way rather than two ways that look alike until they don't.

What genau keeps elsewhere and this has to carry is the phase. Genau's engine
advances it against the clip's beats; here there is no clip, so the motion
free-runs on the driver's clock and the phase rides along with the dials, in
:class:`Motion`.

Hands-free is player_core's too: :mod:`player_core.cruise_control` hands the
device a motion that is several waves summed, each with its own travel, center
and speed, and each of those always on its way somewhere else
(:mod:`player_core.wave_stack` is the arithmetic under it). While it is engaged
the stack is what the device follows and the dials only report what the sum came
to; the rest of the time the motion is the single hand-driven wave it has always
been. :mod:`player_core.learned_motion` is the other takeover: phrases of real
scripting in place of the waveform, played inside the dials' range and at the
speed dial's pace, and never on together with cruise control.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core import cruise_control, learned_motion, wave_stack  # noqa: E402
from player_core.cruise_control import CruiseControlState  # noqa: E402
from player_core.learned_motion import LearnedMotionState, load_default_model  # noqa: E402
from player_core.robot_hand import (  # noqa: E402
    MAX_SPEED,
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
    set_speed,
)

__all__ = [
    "MAX_SPEED",
    "MIN_SPEED",
    "CruiseControlState",
    "Motion",
    "RobotHandState",
    "WaveformShape",
    "adjust_amplitude",
    "adjust_center",
    "adjust_speed",
    "advance",
    "bpm_for_speed",
    "cycle_shape",
    "disable_cruise_control",
    "disable_learned_motion",
    "enable_cruise_control",
    "enable_learned_motion",
    "position",
    "position_ahead",
    "quarter_offset",
    "set_amplitude",
    "set_center",
    "set_speed",
    "tick_cruise_control",
    "tick_learned_motion",
    "toggle_cruise_control",
    "toggle_learned_motion",
    "trace",
]


@dataclass
class Motion:
    """The live motion: genau's dials, cruise control's waves, and the phase.

    The stack has a clock of its own — the motion's seconds rather than the
    wall's, which stand still while the device is parked — and that lives with
    cruise control, since everything timed against it does.
    """

    state: RobotHandState = field(default_factory=RobotHandState)
    cruise: CruiseControlState = field(default_factory=CruiseControlState)
    # Its model is read from the package the first time it is switched on.
    learned: LearnedMotionState = field(default_factory=LearnedMotionState)
    phase: float = 0.0

    @property
    def bpm(self) -> float:
        return self.state.bpm

    @property
    def clock(self) -> float:
        """The motion's own seconds — what the stack's ramps are timed
        against, and so what a sample of it is taken at."""
        return self.cruise.clock


def advance(motion: Motion, dt_s: float) -> None:
    """Carry the single wave's phase forward by ``dt_s`` seconds of motion.

    The stacked motion's phases are carried by its own tick below, which is
    where its clock is: the two apps that share cruise control hand it a wall
    time and nothing else.
    """
    motion.phase = phase_advanced(motion.phase, motion.state.bpm, dt_s)


def tick_cruise_control(motion: Motion, now: float) -> None:
    """Let the dice move the motion, if cruise control has it."""
    cruise_control.tick_cruise_control(motion.state, motion.cruise, now,
                                       phase=motion.phase)


def tick_learned_motion(motion: Motion, now: float) -> None:
    """Let the phrases carry the motion, if the learned motion has it.  The
    first phrase begins where the wave already has the device, so the takeover
    cannot be felt."""
    learned_motion.tick_learned_motion(
        motion.state, motion.learned, now, start_fraction=_envelope_fraction(motion))


def toggle_cruise_control(motion: Motion) -> None:
    """Hands off, or hands back on — taking the motion over from where the dials
    already have it, and handing the single wave back at the phase of the wave
    that was carrying most of the travel, so neither seam is felt."""
    if motion.cruise.active:
        disable_cruise_control(motion)
    else:
        enable_cruise_control(motion)


def enable_cruise_control(motion: Motion) -> None:
    """Hands off, whichever way the switch was standing — what a spoken "cruise
    on" is, where the toggle above is what a key press is.  The learned motion
    lets go: the two are never on together."""
    learned_motion.disable_learned_motion(motion.learned)
    cruise_control.enable_cruise_control(motion.cruise)


def toggle_learned_motion(motion: Motion) -> None:
    """Hands off to the scripts, or back — genau's ``;``."""
    if motion.learned.active:
        disable_learned_motion(motion)
    else:
        enable_learned_motion(motion)


def enable_learned_motion(motion: Motion) -> None:
    """Hands off to the scripts, whichever way the switch was standing.  Cruise
    control lets go the way it always does, handing the wave its phase."""
    disable_cruise_control(motion)
    if motion.learned.model is None:
        motion.learned.model = load_default_model()
    learned_motion.enable_learned_motion(motion.learned)


def disable_learned_motion(motion: Motion) -> None:
    learned_motion.disable_learned_motion(motion.learned)


def disable_cruise_control(motion: Motion) -> None:
    """Hands back on, whichever way the switch was standing."""
    _picked_up(motion, cruise_control.disable_cruise_control(motion.cruise))


def _picked_up(motion: Motion, phase: float | None) -> None:
    """Cruise control letting go says where the single wave should pick up."""
    if phase is not None:
        motion.phase = phase


def quarter_offset(motion: Motion) -> None:
    """Jump a quarter cycle — genau's ``\\`` key, for when the motion is out of
    step with what is on screen and you want it moved rather than restarted."""
    motion.phase = (motion.phase + 0.25) % 1.0
    for wave in motion.cruise.stack.waves:
        wave.phase = (wave.phase + 0.25) % 1.0


def position(motion: Motion) -> float:
    """Where the motion is now, 0-100 — the scale
    :func:`origenerator.osr2.format_position` takes."""
    if motion.learned.active:
        return learned_motion.position(motion.learned, motion.state)
    return _wave_position(motion)


def _wave_position(motion: Motion) -> float:
    """Where the wave has the device — cruise control's sum while it has the
    motion, the single wave otherwise."""
    # Read the stack once: the driver's clock thread can swap it out from
    # under a repaint, and asking twice can be answered twice differently.
    stack = motion.cruise.stack
    if stack:
        return wave_stack.position(stack, motion.clock)
    return _at(motion, motion.phase)


def _envelope_fraction(motion: Motion) -> float:
    """How far up the dials' envelope the wave has the device, 0 at its floor
    and 1 at its ceiling — where the learned motion's first phrase begins."""
    state = motion.state
    if state.amplitude <= 0:
        return 0.0
    low = max(0.0, state.center - state.amplitude / 2)
    span = min(100.0, state.center + state.amplitude / 2) - low
    return (_wave_position(motion) - low) / span if span > 0 else 0.0


def position_ahead(motion: Motion, lead_s: float) -> float:
    """Where the motion will be ``lead_s`` seconds from now, 0-100.

    This, not :func:`position`, is what a device command should aim at: the OSR2
    is told a place and how long to take getting there, so the place has to be
    one it is actually due to be at when the time is up. Aimed at the present it
    can only ever chase.
    """
    if motion.learned.active:
        return learned_motion.position(motion.learned, motion.state, lead_s)
    stack = motion.cruise.stack
    if stack:
        return wave_stack.position_ahead(stack, motion.clock, lead_s)
    return _at(motion, motion.phase + lead_s * motion.state.bpm / 60.0)


def trace(motion: Motion, samples: int, span_s: float) -> list[float]:
    """The motion sampled forward from now as 0-1 heights — the drive readout's
    picture of the motion the device is being sent, ``span_s`` seconds of it."""
    if motion.learned.active:
        return learned_motion.trace(motion.learned, motion.state, samples, span_s)
    stack = motion.cruise.stack
    if stack:
        return wave_stack.trace(stack, motion.clock, samples, span_s)
    span_cycles = span_s * motion.state.bpm / 60.0
    return [
        _at(motion, motion.phase + (i / max(1, samples - 1)) * span_cycles) / 100.0
        for i in range(samples)
    ]


def _at(motion: Motion, phase: float) -> float:
    state = motion.state
    return 100.0 * position_fraction(
        phase, shape=state.shape, amplitude=state.amplitude, center=state.center)
