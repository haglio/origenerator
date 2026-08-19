"""The stroke this app drives the OSR2 with — genau's, plus the phase.

The slideshow shows images, and an image gives the device nothing to follow, so
this supplies the motion instead. None of the motion is written
here: the waveform, the speed dial's exponential map, the amplitude and centre
arithmetic and the hands-free variation of all three are
:mod:`player_core.direct_control` and :mod:`player_core.cruise_control` — genau's
own, moved there so both apps stroke the same way rather than two ways that look
alike until they don't.

What genau keeps elsewhere and this has to carry is the phase. Genau's engine
advances it against the clip's beats; here there is no clip, so the stroke
free-runs on the driver's clock and the phase rides along with the dials, in
:class:`Stroke`. The two sampling helpers below are the driver's and the
readout's questions of that phase — where the device is due to be, and what the
next few seconds look like.
"""

from dataclasses import dataclass, field

from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core.cruise_control import (  # noqa: E402
    CruiseControlState, disable_cruise_control, enable_cruise_control,
    tick_cruise_control, toggle_cruise_control,
)
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
    """The live stroke: genau's dials, cruise control's hands on them, and how
    far through the current cycle the phase has run."""

    state: DirectControlState = field(default_factory=DirectControlState)
    cruise: CruiseControlState = field(default_factory=CruiseControlState)
    phase: float = 0.0

    @property
    def bpm(self) -> float:
        return self.state.bpm


def advance(stroke: Stroke, dt_s: float) -> None:
    """Carry the phase forward by ``dt_s`` seconds of stroking."""
    stroke.phase = phase_advanced(stroke.phase, stroke.state.bpm, dt_s)


def quarter_offset(stroke: Stroke) -> None:
    """Jump a quarter cycle — genau's ``\\`` key, for when the stroke is out of
    step with what is on screen and you want it moved rather than restarted."""
    stroke.phase = (stroke.phase + 0.25) % 1.0


def position(stroke: Stroke) -> float:
    """Where the stroke is now, 0-100 — the scale
    :func:`origenerator.osr2.format_position` takes."""
    return _at(stroke, stroke.phase)


def position_ahead(stroke: Stroke, lead_s: float) -> float:
    """Where the stroke will be ``lead_s`` seconds from now, 0-100.

    This, not :func:`position`, is what a device command should aim at: the OSR2
    is told a place and how long to take getting there, so the place has to be
    one it is actually due to be at when the time is up. Aimed at the present it
    can only ever chase.
    """
    return _at(stroke, stroke.phase + lead_s * stroke.state.bpm / 60.0)


def trace(stroke: Stroke, samples: int, span_s: float) -> list[float]:
    """The stroke sampled forward from now as 0-1 heights — the drive readout's
    picture of the motion the device is being sent, ``span_s`` seconds of it."""
    span_cycles = span_s * stroke.state.bpm / 60.0
    return [
        _at(stroke, stroke.phase + (i / max(1, samples - 1)) * span_cycles) / 100.0
        for i in range(samples)
    ]


def _at(stroke: Stroke, phase: float) -> float:
    state = stroke.state
    return 100.0 * position_fraction(
        phase, shape=state.shape, amplitude=state.amplitude, center=state.center)
