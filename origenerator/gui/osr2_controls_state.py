"""What this app tells the Funestras' console painter, and what a press on it means.

The OSR2 controls are drawn in two places here — alone at the top left of Core,
and on the HUD a slideshow wears — so what goes ON them and what a press takes
OFF them are written once, here,
rather than once per surface.

Nothing is drawn here. :class:`funestra.console_hud.ConsolePainter` and the
sections it is built from do the drawing; this only says what they are drawing:
the motion's bars sampled forward, the funscript's line where a script has the
device, and whether the app's one OSR2 switch is on.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace

from app_support.osr2_device import Osr2Mode, Osr2Trouble
from funestra import drive_layout
from funestra.console import (
    BROKER_PRESS,
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_UNANSWERED,
    OSR2_DRIVING,
    OSR2_PARKED,
    ConsoleModel,
    aim_row,
    osr2_controls,
)
from funestra.console_hud import ConsoleHud, ConsolePainter
from funestra.drive_readout import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_NOTHING,
    DRIVEN_BY_ROBOT_HAND,
    DriveHud,
)
from funestra.modes import MainMode, Osr2State
from funestra.robot_hand import POSITION_MAX, control_limits

from origenerator import motion_engine, osr2
from origenerator.osr2_controls_commands import level_asked_for, max_intensity_asked_for

# Which press on the OSR2 controls' switch asks for which state, read off
# funestra's own mapping so a press cannot drift from the button that lights.
OSR2_CONTROL_BY_COMMAND = {verb: state for state, verb in OSR2_CONTROL_BUTTONS.items()}

_TRACE_SECONDS = 12.0
# The trace scrolls with the phase, so whichever surface is showing it
# redraws on this beat -- and only while something is driving.
REPAINT_MS = 100


def drive_hud(state, active: bool) -> DriveHud:
    """The live motion as the readout's own view of it.

    The bars, where the device is, and the motion sampled forward — the same
    samples it is being sent, so the trace is the motion rather than a drawing
    of it. ``driven`` is what dims the whole readout: nothing reaching the
    device is a drawing of a motion nobody is making, and it goes gray exactly
    as Fun Time's does.
    """
    heights, slide = motion_engine.trace_window(state, drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    return DriveHud(
        **_bars_drawn(state.state),
        position=round(POSITION_MAX * motion_engine.position(state) / 100),
        driven=DRIVEN_BY_ROBOT_HAND if active else DRIVEN_BY_NOTHING,
        trace_seconds=_TRACE_SECONDS,
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
    return DriveHud(
        **_bars_drawn(motion.state),
        position=round(POSITION_MAX * (heights[0] if heights else 0.0)),
        driven=DRIVEN_BY_FUNSCRIPT, trace_seconds=_TRACE_SECONDS, waveform=heights)


def _bars_drawn(bars) -> dict:
    return dict(speed=bars.speed, amplitude=bars.amplitude, center=bars.center,
                shape=bars.shape.value, max_intensity=bars.max_intensity,
                **asdict(control_limits(bars)))


def osr2_controls_hud(motion, *, device: Osr2Mode = Osr2Mode.CONTROLLED, trouble: Osr2Trouble | None = None,
                control: str = OSR2_CONTROL_UNANSWERED, script=None,
                broker_running: bool = True) -> ConsoleHud:
    """The OSR2 controls as Fun Time's console painter takes them.

    ``mode`` is genau because that is what this is: a self-generated motion over
    what is on screen, with no Nau playlist under it.

    ``script`` is the funscript driver, when this app has one: while it has the
    device the readout is the script's line rather than the motion's, and the
    OSR2 row says FunScript -- the motion is stopped, and drawing it would be a
    drawing of something nobody is sending.
    """
    shown = osr2_controls_state(motion, device=device, trouble=trouble, control=control, script=script,
                             broker_running=broker_running)
    return ConsoleHud(
        console=ConsoleModel(
            main_mode=MainMode.GENAU,
            osr2=shown.osr2, osr2_control=control, paused=shown.paused,
            osr2_rows=shown.osr2_rows, osr2_controls=shown.osr2_controls,
            max_intensity=shown.max_intensity,
        ),
        drive=shown.drive,
    )


@dataclass(frozen=True)
class Osr2ControlsState:
    """The OSR2 controls' state: the rows that aim the OSR2, who has the device,
    and the motion being sent.

    Handed to the one HUD a slideshow wears (:mod:`origenerator.gui.slideshow_hud`) so
    it says all of it without a second HUD underneath, and used to build the
    OSR2 controls in Core.
    """

    osr2_rows: tuple
    osr2: str
    # Whether the app's one OSR2 switch is on (driving) or off (parked), or empty where
    # nobody handed a switch over -- the HUD resolves the pair into one word.
    osr2_control: str
    drive: DriveHud
    max_intensity: int
    paused: bool = False
    osr2_controls: tuple = ()


def osr2_controls_state(motion, *, device: Osr2Mode = Osr2Mode.CONTROLLED,
                     trouble: Osr2Trouble | None = None,
                     control: str = OSR2_CONTROL_UNANSWERED, script=None,
                     broker_running: bool = True) -> Osr2ControlsState:
    """What the device is doing, as a HUD takes it — see :class:`Osr2ControlsState`.

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
    return Osr2ControlsState(
        osr2_control=control,
        osr2_rows=(aim_row(learned=motion.state.learned.active,
                           shape=motion.state.state.shape.value, control=control),),
        osr2_controls=osr2_controls(broker_running=broker_running),
        osr2=Osr2State.of(device, funscript_driving=scripted, trouble=trouble),
        drive=(script_hud(script, motion.state) if scripted
               else drive_hud(motion.state, driving)),
        max_intensity=motion.state.state.max_intensity,
        paused=motion.parked_by_the_pause or (script is not None and script.parked_by_the_pause),
    )


def osr2_controls_room(motion) -> tuple[int, int]:
    driving = SimpleNamespace(active=True, state=motion.state, parked_by_the_pause=False)
    return ConsolePainter(device_only=True).rgba(osr2_controls_hud(driving, control=OSR2_DRIVING))[1]


def post_device_action(action: str, *, motion, control=None) -> bool:
    """Do what a press on the OSR2 controls asks, wherever they were drawn.

    The verbs are the Funestras' console's own — the same strings Fun Time routes to
    whichever Funestra owns them — and this routes them to what this app has: the
    motion for everything about the motion, and the app's one OSR2 switch for
    the control-state group and the max intensity.

    *control* is that switch, or None where nobody handed one over — a HUD
    outside the gallery, and a test's bare OSR2 controls.  The two holds still reach
    the motion there, which is what such a HUD can do about the device.

    Answers whether this was one of the Funestras' console's verbs at all, so a HUD
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
    elif action == BROKER_PRESS:
        osr2.press_the_broker()
    elif action == "robot_hand_toggle_learned":
        motion.toggle_learned()
    elif action == "robot_hand_cycle_shape":
        motion.cycle_shape()
    else:
        return False
    return True


def _ask_for_control(state: str, motion, control) -> None:
    """A press on the OSR2 switch.  With no switch handed over there is still
    the motion to park, which is what a HUD outside a gallery can do about the
    device."""
    if control is not None:
        control.set_state(state)
    elif state == OSR2_DRIVING:
        motion.release()
    elif state == OSR2_PARKED:
        motion.hold(OSR2_PARKED)
