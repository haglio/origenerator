"""The stroke this app drives the OSR2 with — genau's wave, and what rides it.

The slideshow shows images, and an image gives the device nothing to follow, so
this supplies the motion instead. The waveform itself is not written here: the
shapes, the speed dial's exponential map and the amplitude and center arithmetic
are :mod:`player_core.direct_control` — genau's own, shared so both apps stroke
the same way rather than two ways that look alike until they don't.

What genau keeps elsewhere and this has to carry is the phase. Genau's engine
advances it against the clip's beats; here there is no clip, so the stroke
free-runs on the driver's clock and the phase rides along with the dials, in
:class:`Stroke`.

Hands-free is player_core's too: :mod:`player_core.cruise_control` hands the
device a stroke that is several waves summed, each with its own travel, center
and speed, and each of those always on its way somewhere else
(:mod:`player_core.wave_stack` is the arithmetic under it). While it is engaged
the stack is what the device follows and the dials only report what the sum came
to; the rest of the time the stroke is the single hand-driven wave it has always
been.
"""

from dataclasses import dataclass, field

from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core import cruise_control, wave_stack  # noqa: E402
from player_core.cruise_control import CruiseControlState  # noqa: E402
from player_core.direct_control import (  # noqa: E402
    MAX_SPEED, MIN_SPEED, DirectControlState, WaveformShape, adjust_amplitude,
    adjust_center, adjust_speed, bpm_for_speed, cycle_shape, phase_advanced,
    position_fraction, set_amplitude, set_center, set_speed,
)

__all__ = [
    "MAX_SPEED", "MIN_SPEED", "CruiseControlState", "DirectControlState",
    "Stroke", "WaveformShape", "adjust_amplitude", "adjust_center",
    "adjust_speed", "advance", "bpm_for_speed", "cycle_shape",
    "disable_cruise_control", "enable_cruise_control", "position",
    "position_ahead", "quarter_offset", "set_amplitude", "set_center",
    "set_speed", "tick_cruise_control", "toggle_cruise_control", "trace",
]


@dataclass
class Stroke:
    """The live stroke: genau's dials, cruise control's waves, and the phase.

    The stack has a clock of its own — the stroke's seconds rather than the
    wall's, which stand still while the device is parked — and that lives with
    cruise control, since everything timed against it does.
    """

    state: DirectControlState = field(default_factory=DirectControlState)
    cruise: CruiseControlState = field(default_factory=CruiseControlState)
    phase: float = 0.0

    @property
    def bpm(self) -> float:
        return self.state.bpm

    @property
    def clock(self) -> float:
        """The stroke's own seconds — what the stack's ramps are timed
        against, and so what a sample of it is taken at."""
        return self.cruise.clock


def advance(stroke: Stroke, dt_s: float) -> None:
    """Carry the single wave's phase forward by ``dt_s`` seconds of stroking.

    The stacked stroke's phases are carried by its own tick below, which is
    where its clock is: the two apps that share cruise control hand it a wall
    time and nothing else.
    """
    stroke.phase = phase_advanced(stroke.phase, stroke.state.bpm, dt_s)


def tick_cruise_control(stroke: Stroke, now: float) -> None:
    """Let the dice move the stroke, if cruise control has it."""
    cruise_control.tick_cruise_control(stroke.state, stroke.cruise, now,
                                       phase=stroke.phase)


def toggle_cruise_control(stroke: Stroke) -> None:
    """Hands off, or hands back on — taking the stroke over from where the dials
    already have it, and handing the single wave back at the phase of the wave
    that was carrying most of the travel, so neither seam is felt."""
    _picked_up(stroke, cruise_control.toggle_cruise_control(stroke.cruise))


def enable_cruise_control(stroke: Stroke) -> None:
    """Hands off, whichever way the switch was standing — what a spoken "cruise
    on" is, where the toggle above is what a key press is."""
    cruise_control.enable_cruise_control(stroke.cruise)


def disable_cruise_control(stroke: Stroke) -> None:
    """Hands back on, whichever way the switch was standing."""
    _picked_up(stroke, cruise_control.disable_cruise_control(stroke.cruise))


def _picked_up(stroke: Stroke, phase: float | None) -> None:
    """Cruise control letting go says where the single wave should pick up."""
    if phase is not None:
        stroke.phase = phase


def quarter_offset(stroke: Stroke) -> None:
    """Jump a quarter cycle — genau's ``\\`` key, for when the stroke is out of
    step with what is on screen and you want it moved rather than restarted."""
    stroke.phase = (stroke.phase + 0.25) % 1.0
    for wave in stroke.cruise.stack.waves:
        wave.phase = (wave.phase + 0.25) % 1.0


def position(stroke: Stroke) -> float:
    """Where the stroke is now, 0-100 — the scale
    :func:`origenerator.osr2.format_position` takes."""
    # Read the stack once: the driver's clock thread can swap it out from
    # under a repaint, and asking twice can be answered twice differently.
    stack = stroke.cruise.stack
    if stack:
        return wave_stack.position(stack, stroke.clock)
    return _at(stroke, stroke.phase)


def position_ahead(stroke: Stroke, lead_s: float) -> float:
    """Where the stroke will be ``lead_s`` seconds from now, 0-100.

    This, not :func:`position`, is what a device command should aim at: the OSR2
    is told a place and how long to take getting there, so the place has to be
    one it is actually due to be at when the time is up. Aimed at the present it
    can only ever chase.
    """
    stack = stroke.cruise.stack
    if stack:
        return wave_stack.position_ahead(stack, stroke.clock, lead_s)
    return _at(stroke, stroke.phase + lead_s * stroke.state.bpm / 60.0)


def trace(stroke: Stroke, samples: int, span_s: float) -> list[float]:
    """The stroke sampled forward from now as 0-1 heights — the drive readout's
    picture of the motion the device is being sent, ``span_s`` seconds of it."""
    stack = stroke.cruise.stack
    if stack:
        return wave_stack.trace(stack, stroke.clock, samples, span_s)
    span_cycles = span_s * stroke.state.bpm / 60.0
    return [
        _at(stroke, stroke.phase + (i / max(1, samples - 1)) * span_cycles) / 100.0
        for i in range(samples)
    ]


def _at(stroke: Stroke, phase: float) -> float:
    state = stroke.state
    return 100.0 * position_fraction(
        phase, shape=state.shape, amplitude=state.amplitude, center=state.center)
