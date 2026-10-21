"""What this app tells the Funestras' console painter, and what a press on it means.

The console is drawn in two places here — its OSR2 section alone at the top left
of the main window, and that section with the pace on the panel a slideshow wears — so
what goes ON the console and what a press takes OFF it are written once, here,
rather than once per surface.

Nothing is drawn here. :class:`funestra.console_hud.ConsolePainter` and the
sections it is built from do the drawing; this only says what they are drawing:
the pace an unlocked slide moves on at, the motion's bars sampled forward, the
funscript's line where a script has the device, and whether the app's one OSR2
switch is on.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app_support.osr2_device import Osr2Mode, Osr2Trouble
from funestra import drive_layout
from funestra.console import (
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_UNANSWERED,
    OSR2_DRIVING,
    OSR2_PARKED,
    ROW_LABEL_W,
    VALUE_W,
    ConsoleModel,
    aim_row,
)
from funestra.console_hud import ConsoleHud, ConsolePainter
from funestra.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_NOTHING,
    DRIVEN_BY_ROBOT_HAND,
    DriveHud,
)
from funestra.hud_button import Button
from funestra.modes import MainMode, Osr2State
from funestra.robot_hand import POSITION_MAX

from origenerator import motion_engine
from origenerator.console_commands import level_asked_for, max_intensity_asked_for
from origenerator.gui.slideshow_pace import STEP_S as DWELL_STEP_S

# Which press on the console's OSR2 switch asks for which state, read off
# funestra's own mapping so a press cannot drift from the button that lights.
OSR2_CONTROL_BY_COMMAND = {verb: state for state, verb in OSR2_CONTROL_BUTTONS.items()}

_TRACE_SECONDS = 12.0
# The trace scrolls with the phase, so whichever surface is showing it
# redraws on this beat -- and only while something is driving.
REPAINT_MS = 100


def _limits(state) -> drive_layout.Limits:
    """Which bars have run out of road — what dims the mark that would now do
    nothing."""
    bars = state.state
    half = bars.amplitude // 2
    return drive_layout.Limits(
        spd_at_min=bars.speed <= motion_engine.MIN_SPEED,
        spd_at_max=bars.speed >= motion_engine.MAX_SPEED,
        amp_at_min=bars.amplitude <= 0,
        amp_at_max=bars.amplitude >= 100,
        ctr_at_min=bars.intended_center <= half,
        ctr_at_max=bars.intended_center >= 100 - half,
    )


def drive_hud(state, active: bool) -> DriveHud:
    """The live motion as the readout's own view of it.

    The bars, where the device is, and the motion sampled forward — the same
    samples it is being sent, so the trace is the motion rather than a drawing
    of it. ``driven`` is what dims the whole readout: nothing reaching the
    device is a picture of a motion nobody is making, and it goes gray exactly
    as Fun Time's does.
    """
    bars = state.state
    limits = _limits(state)
    heights, slide = motion_engine.trace_window(state, drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    return DriveHud(
        speed=bars.speed, amplitude=bars.amplitude, center=bars.center,
        shape=bars.shape.value,
        position=round(POSITION_MAX * motion_engine.position(state) / 100),
        driven=DRIVEN_BY_ROBOT_HAND if active else DRIVEN_BY_NOTHING,
        trace_seconds=_TRACE_SECONDS,
        spd_at_min=limits.spd_at_min, spd_at_max=limits.spd_at_max,
        amp_at_min=limits.amp_at_min, amp_at_max=limits.amp_at_max,
        ctr_at_min=limits.ctr_at_min, ctr_at_max=limits.ctr_at_max,
        waveform=tuple(heights[:drive_layout.TRACE_SAMPLES]),
        slide=slide,
        edge=heights[drive_layout.TRACE_SAMPLES],
    )


def script_hud(script, motion) -> DriveHud:
    """The readout while a funscript has the device: the script's own line from
    the playhead forward, in the green every scripted thing in this family is
    drawn in.

    The bars beside it stay the motion's.  They are what driving puts back the
    moment the script is done, and the readout dims every one of them anyway
    while something other than the motion is sending.
    """
    heights = script.trace(drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    bars = motion.state
    return DriveHud(
        speed=bars.speed, amplitude=bars.amplitude, center=bars.center,
        shape=bars.shape.value,
        position=round(POSITION_MAX * (heights[0] if heights else 0.0)),
        driven=DRIVEN_BY_FUNSCRIPT, trace_seconds=_TRACE_SECONDS, waveform=heights)


def console_hud(motion, *, device: Osr2Mode = Osr2Mode.CONTROLLED, trouble: Osr2Trouble | None = None,
                control: str = OSR2_CONTROL_UNANSWERED, script=None) -> ConsoleHud:
    """The console's OSR2 section as Fun Time's painter takes it.

    ``mode`` is genau because that is what this is: a self-generated motion over
    what is on screen, with no Nau playlist under it.

    ``script`` is the funscript driver, when this app has one: while it has the
    device the readout is the script's line rather than the motion's, and the
    OSR2 row says FunScript -- the motion is stopped, and drawing it would be a
    picture of something nobody is sending.

    ``device`` is what the OSR2 reads as (:func:`origenerator.osr2.device_mode`):
    switched off, running its own auto mode, or taking this app's commands. A
    motion running with the device off is a motion nobody is receiving, and the
    console says so exactly as Fun Time's does: the OSR2 row reads "Off", or why
    the Broker cannot hear it (``trouble``), and the painter takes that as
    nothing driving, which grays the readout and holds the trace still. The
    motion goes on — it cannot see the device either way — so this is the only
    thing standing between a switched-off OSR2 and a console animating a blue
    wave nothing is riding.
    """
    shown = slideshow_device(motion, device=device, trouble=trouble, control=control, script=script)
    return ConsoleHud(
        console=ConsoleModel(
            main_mode=MainMode.GENAU,
            osr2=shown.osr2, osr2_control=control, paused=shown.paused,
            osr2_rows=shown.osr2_rows,
            max_intensity=shown.max_intensity,
        ),
        drive=shown.drive,
    )


@dataclass(frozen=True)
class SlideshowDevice:
    """The device half of this app's console: the rows that aim the OSR2, who
    has the device, and the motion being sent -- and on a slideshow's panel, the pace.

    Handed to the one panel a slideshow wears (:mod:`origenerator.gui.slideshow_panel`) so
    it says all of it without a second panel underneath, and used to build the
    console's OSR2 section in the main window.
    """

    osr2_rows: tuple
    osr2: str
    # Whether the app's one OSR2 switch is on (driving) or off (parked), or empty where
    # nobody handed a switch over -- the panel resolves the pair into one word.
    osr2_control: str
    drive: DriveHud
    max_intensity: int
    # The pace an unlocked slide moves on at -- about the SET, so it rides with
    # the rows that step it rather than with the device.
    rows: tuple = ()
    paused: bool = False


def slideshow_device(motion, *, pace_s: int | None = None, device: Osr2Mode = Osr2Mode.CONTROLLED,
                     trouble: Osr2Trouble | None = None,
                     control: str = OSR2_CONTROL_UNANSWERED, script=None) -> SlideshowDevice:
    """What the device is doing, as a panel takes it — see :class:`SlideshowDevice`.

    ``script`` is the funscript driver, when this app has one: while it has the
    device the readout is the script's line rather than the motion's, and the
    line says FunScript.  ``device`` is what the OSR2 reads as; switched off
    nothing here is being received, so the line reads Off, or why the Broker
    cannot hear it (``trouble``), the readout grays and the trace holds still
    rather than animating a wave nobody is riding, and in its own auto mode the
    line reads Auto.
    """
    on = device is not Osr2Mode.OFF
    scripted = script is not None and script.active and on
    driving = motion.active and on and not scripted
    return SlideshowDevice(
        osr2_control=control,
        rows=() if pace_s is None else (pace_row(pace_s),),
        osr2_rows=(aim_row(learned=motion.state.learned.active,
                           shape=motion.state.state.shape.value, control=control),),
        osr2=Osr2State.of(device, funscript_driving=scripted, trouble=trouble),
        drive=(script_hud(script, motion.state) if scripted
               else drive_hud(motion.state, driving)),
        max_intensity=motion.state.state.max_intensity,
        paused=motion.parked_by_the_pause or (script is not None and script.parked_by_the_pause),
    )


def panel_room(motion) -> tuple[int, int]:
    driving = SimpleNamespace(active=True, state=motion.state, parked_by_the_pause=False)
    return ConsolePainter(device_only=True).rgba(console_hud(driving, control=OSR2_DRIVING))[1]


def pace_row(pace_s: int) -> tuple[Button, ...]:
    return (
        Button("", "Clip seconds", "", width=ROW_LABEL_W),
        Button("genau_clip_seconds_down", "−", "Move on sooner", group_break=True),
        Button("", f"{pace_s}s", "", width=VALUE_W),
        Button("genau_clip_seconds_up", "+", "Leave each clip longer"),
    )


_PACE_STEPS = {"genau_clip_seconds_up": DWELL_STEP_S, "genau_clip_seconds_down": -DWELL_STEP_S}


def post_pace_action(action: str, host) -> bool:
    """Step *host*'s pace for a press on the clip-seconds pair, and say whether
    the press was one of that pair."""
    if action not in _PACE_STEPS:
        return False
    host.set_dwell_s(host.dwell_s + _PACE_STEPS[action])  # the pace clamps its own ends
    return True


def post_device_action(action: str, *, motion, control=None) -> bool:
    """Do what a press on the console's OSR2 section asks, wherever it was drawn.

    The verbs are the console's own — the same strings Fun Time routes to
    whichever Funestra owns them — and this routes them to what this app has: the
    motion for everything about the motion, and the app's one OSR2 switch for
    the control-state group and the max intensity.

    *control* is that switch, or None where nobody handed one over — a panel
    outside the gallery, and a test's bare console.  The two holds still reach
    the motion there, which is what such a panel can do about the device.

    Answers whether this was one of the console's verbs at all, so a panel
    carrying other buttons beside them can go on routing the rest.
    """
    if not action:
        return False
    max_intensity = max_intensity_asked_for(action)
    if max_intensity is not None:
        (control if control is not None else motion).set_max_intensity(max_intensity)
        return True
    level = level_asked_for(action)
    if level is not None:
        {drive_layout.AMPLITUDE: motion.set_amplitude,
         drive_layout.CENTER: motion.set_center,
         drive_layout.SPEED: motion.set_speed}[level.axis](level.value)
        return True
    step = {
        "robot_hand_speed_up": (motion.adjust_speed, 5),
        "robot_hand_speed_down": (motion.adjust_speed, -5),
        "robot_hand_amplitude_up": (motion.adjust_amplitude, 10),
        "robot_hand_amplitude_down": (motion.adjust_amplitude, -10),
        "robot_hand_center_up": (motion.adjust_center, 5),
        "robot_hand_center_down": (motion.adjust_center, -5),
    }.get(action)
    if step is not None:
        step[0](step[1])
    elif action in OSR2_CONTROL_BY_COMMAND:
        _ask_for_control(OSR2_CONTROL_BY_COMMAND[action], motion, control)
    elif action == "robot_hand_toggle_learned":
        motion.toggle_learned()
    elif action == "robot_hand_cycle_shape":
        motion.cycle_shape()
    elif action == "quarter_button":
        motion.quarter_offset()
    else:
        return False
    return True


def _ask_for_control(state: str, motion, control) -> None:
    """A press on the OSR2 switch.  With no switch handed over there is still
    the motion to park, which is what a panel outside a gallery can do about the
    device."""
    if control is not None:
        control.set_state(state)
    elif state == OSR2_DRIVING:
        motion.release()
    elif state == OSR2_PARKED:
        motion.hold(OSR2_PARKED)
