"""What this app tells the players' console painter, and what a press on it means.

The console is drawn in two places here — the foot of the main window, where
there is no show to step, and a fullscreen show, where the show's own panel
carries the device half of it — so what goes ON the console and what a press
takes OFF it are written once, here, rather than once per surface.

Nothing is drawn here. :class:`player_core.console_hud.ConsolePainter` and the
sections it is built from do the drawing; this only says what they are drawing:
the pace an unlocked slide moves on at, the motion's dials sampled forward, the
funscript's line where a script has the device, and which of the four control
states the app's one OSR2 switch is in.
"""

from __future__ import annotations

from dataclasses import dataclass

from player_core import drive_layout
from player_core.console import (
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_UNANSWERED,
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
    ConsoleModel,
)
from player_core.console_hud import ConsoleHud, ConsolePainter, ModeHud
from player_core.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_NOTHING,
    DRIVEN_BY_ROBOT_HAND,
    DriveHud,
)
from player_core.modes import MainMode, Osr2State
from player_core.robot_hand import (
    PARK_CENTER,
    POSITION_MAX,
    RETRACT_CENTER,
)

from origenerator import motion_engine
from origenerator.gui.console_buttons import console_rows, device_rows
from origenerator.gui.slideshow_pace import STEP_S as DWELL_STEP_S

# Which of the console's four control buttons asks for which state, read off
# player_core's own mapping so a press cannot drift from the button that lights.
OSR2_CONTROL_BY_COMMAND = {verb: state for state, verb in OSR2_CONTROL_BUTTONS.items()}

_TRACE_SECONDS = 12.0
# The trace scrolls with the phase, so whichever surface is showing it
# redraws on this beat -- and only while something is driving.
REPAINT_MS = 100


def _limits(state) -> drive_layout.Limits:
    """Which dials have run out of road — what dims the mark that would now do
    nothing."""
    dials = state.state
    half = dials.amplitude // 2
    return drive_layout.Limits(
        spd_at_min=dials.speed <= motion_engine.MIN_SPEED,
        spd_at_max=dials.speed >= motion_engine.MAX_SPEED,
        amp_at_min=dials.amplitude <= 0,
        amp_at_max=dials.amplitude >= 100,
        ctr_at_min=dials.intended_center <= half,
        ctr_at_max=dials.intended_center >= 100 - half,
    )


def drive_hud(state, active: bool, dwell_s: int = 0) -> DriveHud:
    """The live motion as the readout's own view of it.

    The dials, where the device is, and the motion sampled forward — the same
    samples it is being sent, so the trace is the motion rather than a drawing
    of it. ``driven`` is what dims the whole readout: nothing reaching the
    device is a picture of a motion nobody is making, and it goes grey exactly
    as Fun Time's does.
    """
    dials = state.state
    limits = _limits(state)
    heights, slide = motion_engine.trace_window(state, drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    return DriveHud(
        speed=dials.speed, amplitude=dials.amplitude, center=dials.center,
        shape=dials.shape.value,
        position=round(POSITION_MAX * motion_engine.position(state) / 100),
        driven=DRIVEN_BY_ROBOT_HAND if active else DRIVEN_BY_NOTHING,
        advance_interval=dwell_s,
        trace_seconds=_TRACE_SECONDS,
        spd_at_min=limits.spd_at_min, spd_at_max=limits.spd_at_max,
        amp_at_min=limits.amp_at_min, amp_at_max=limits.amp_at_max,
        ctr_at_min=limits.ctr_at_min, ctr_at_max=limits.ctr_at_max,
        waveform=tuple(heights[:drive_layout.TRACE_SAMPLES]),
        slide=slide,
        edge=heights[drive_layout.TRACE_SAMPLES],
    )


def script_hud(script, motion, dwell_s: int) -> DriveHud:
    """The readout while a funscript has the device: the script's own line from
    the playhead forward, in the green every scripted thing in this family is
    drawn in.

    The dials beside it stay the motion's.  They are what driving puts back the
    moment the script is done, and the readout dims every one of them anyway
    while something other than the motion is sending.
    """
    heights = script.trace(drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    dials = motion.state
    return DriveHud(
        speed=dials.speed, amplitude=dials.amplitude, center=dials.center,
        shape=dials.shape.value,
        position=round(POSITION_MAX * (heights[0] if heights else 0.0)),
        driven=DRIVEN_BY_FUNSCRIPT, advance_interval=dwell_s,
        trace_seconds=_TRACE_SECONDS, waveform=heights)


def console_hud(motion, host, *, device_on: bool = True,
                control: str = OSR2_CONTROL_UNANSWERED, script=None) -> ConsoleHud:
    """The whole console as Fun Time's painter takes it.

    ``mode`` is genau because that is what this is: a self-generated motion over
    what is on screen, with no Nau playlist under it. The empty
    :class:`ModeHud` is what leaves the status line saying only whether the
    slide is locked — there is no compilation, no browse order and no length
    filter here to report.

    ``script`` is the funscript driver, when this app has one: while it has the
    device the readout is the script's line rather than the motion's, and the
    OSR2 row says FunScript -- the motion is stopped, and drawing it would be a
    picture of something nobody is sending.

    ``device_on`` is whether the OSR2 is answering at all
    (:func:`origenerator.osr2.device_on`). A motion running with the device off
    is a motion nobody is receiving, and the console says so exactly as Fun
    Time's does: the OSR2 row reads "Off" and the painter takes that as nothing
    driving, which greys the readout and holds the trace still. The motion goes
    on — it cannot see the device either way — so this is the only
    thing standing between a switched-off OSR2 and a console animating a blue
    wave nothing is riding.

    Neither filter switch is offered (both ``None``): the console draws those
    only where the host hands over a set to narrow, and here the show's own HUD
    carries them instead.
    """
    device = show_device(motion, host, device_on=device_on, control=control,
                         script=script)
    return ConsoleHud(
        modes=ModeHud(),
        console=ConsoleModel(
            main_mode=MainMode.GENAU, active=True, locked=host.locked,
            osr2=device.osr2, osr2_control=control,
            advance_interval=host.dwell_s,
            rows=console_rows(locked=host.locked, pace_s=host.dwell_s,
                              control=control,
                              cruise=motion.state.cruise.active,
                              learned=motion.state.learned.active,
                              shape=motion.state.state.shape.value),
        ),
        drive=device.drive,
    )


@dataclass(frozen=True)
class ShowDevice:
    """The device half of this app's console: the pace, the rows that aim the
    OSR2, who has the device, and the motion being sent.

    Handed to the one panel a show wears (:mod:`origenerator.gui.show_hud`) so
    it says all of it without a second panel underneath, and used to build the
    whole console for the surface that has no show under it at all.
    """

    # The pace an unlocked slide moves on at -- about the SET, so it rides with
    # the rows that step it rather than with the device.
    rows: tuple
    # And the rows that aim the OSR2, which ride with the device.
    osr2_rows: tuple
    osr2: str
    # Which of the four states the app's one OSR2 switch is in, or empty where
    # nobody handed a switch over -- the panel resolves the pair into one word.
    osr2_control: str
    drive: DriveHud


def show_device(motion, host, *, device_on: bool = True,
                control: str = OSR2_CONTROL_UNANSWERED, script=None) -> ShowDevice:
    """What the device is doing, as a panel takes it — see :class:`ShowDevice`.

    ``script`` is the funscript driver, when this app has one: while it has the
    device the readout is the script's line rather than the motion's, and the
    line says FunScript.  ``device_on`` is whether the OSR2 is answering at all;
    with it off nothing here is being received, so the line reads Off, the
    readout greys and the trace holds still rather than animating a wave nobody
    is riding.
    """
    scripted = script is not None and script.active and device_on
    driving = motion.active and device_on and not scripted
    pace, aim = device_rows(control=control, pace_s=host.dwell_s,
                            cruise=motion.state.cruise.active,
                            learned=motion.state.learned.active,
                            shape=motion.state.state.shape.value)
    return ShowDevice(
        osr2_control=control,
        rows=(pace,),
        osr2_rows=(aim,),
        osr2=(Osr2State.FUNSCRIPT if scripted
              else Osr2State.ROBOT_HAND if driving else Osr2State.OFF),
        drive=(script_hud(script, motion.state, host.dwell_s) if scripted
               else drive_hud(motion.state, driving, host.dwell_s)),
    )


def panel_size(motion, host, control: str = OSR2_CONTROL_UNANSWERED) -> tuple[int, int]:
    """How big the console draws, which is what the widget has to be."""
    return ConsolePainter().rgba(console_hud(motion, host, control=control))[1]


def post_console_action(action: str, *, motion, host, control=None) -> bool:
    """Do what a press on the console asks, wherever the console was drawn.

    The verbs are the console's own — the same strings Fun Time routes to
    whichever player owns them — and this routes them to what this app has: the
    show (or the pace-only stand-in) for the transport and the pace, the motion
    for everything about the motion, and the app's one OSR2 switch for the
    control-state group.

    *control* is that switch, or None where nobody handed one over — a panel
    outside the gallery, and a test's bare console.  The two holds still reach
    the motion there, which is what such a panel can do about the device.

    Answers whether this was one of the console's verbs at all, so a panel
    carrying other buttons beside them can go on routing the rest.
    """
    if not action:
        return False
    if action.startswith("robot_hand_") and "_" in action[11:]:
        axis, _, value = action[11:].rpartition("_")
        if value.isdigit() and axis in ("amp", "center", "speed"):
            {"amp": motion.set_amplitude, "center": motion.set_center,
             "speed": motion.set_speed}[axis](int(value))
            return True
    step = {
        "robot_hand_speed_up": (motion.adjust_speed, 5),
        "robot_hand_speed_down": (motion.adjust_speed, -5),
        "robot_hand_amplitude_up": (motion.adjust_amplitude, 10),
        "robot_hand_amplitude_down": (motion.adjust_amplitude, -10),
        "robot_hand_center_up": (motion.adjust_center, 5),
        "robot_hand_center_down": (motion.adjust_center, -5),
        "genau_prev_clip": (host.show_step, -1),
        "genau_next_clip": (host.show_step, 1),
    }.get(action)
    if step is not None:
        step[0](step[1])
    elif action in OSR2_CONTROL_BY_COMMAND:
        _ask_for_control(OSR2_CONTROL_BY_COMMAND[action], motion, control)
    elif action == "robot_hand_toggle_cruise":
        motion.toggle_cruise()
    elif action == "robot_hand_toggle_learned":
        motion.toggle_learned()
    elif action == "robot_hand_cycle_shape":
        motion.cycle_shape()
    elif action == "quarter_button":
        motion.quarter_offset()
    elif action == "main_lock":
        host.show_toggle_lock()
    elif action == "genau_weird_clip":
        host.show_cull()
    elif action in ("genau_clip_seconds_up", "genau_clip_seconds_down"):
        delta = DWELL_STEP_S if action.endswith("up") else -DWELL_STEP_S
        host.set_dwell_s(host.dwell_s + delta)  # the pace clamps its own ends
    else:
        return False
    return True


def _ask_for_control(state: str, motion, control) -> None:
    """A press on the control-state group.  With no switch handed over there is
    still the motion to hold, which is what a panel outside a gallery can do
    about the device."""
    if control is not None:
        control.set_state(state)
    elif state == OSR2_DRIVING:
        motion.release()
    elif state in (OSR2_PARKED, OSR2_RETRACTED):
        motion.hold(PARK_CENTER if state == OSR2_PARKED else RETRACT_CENTER)
