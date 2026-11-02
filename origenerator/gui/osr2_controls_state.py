from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace

from app_support.osr2_device import Osr2Mode, Osr2Trouble
from funestra import drive_layout
from funestra.main_hud import (
    BROKER_PRESS,
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_UNANSWERED,
    OSR2_DRIVING,
    OSR2_PARKED,
    MainHudModel,
    aim_row,
    osr2_controls,
)
from funestra.main_hud_painter import MainHud, MainHudPainter
from funestra.modes import MainMode, Osr2State
from funestra.osr2_visualizer import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_NOTHING,
    DRIVEN_BY_ROBOT_HAND,
    DriveHud,
)
from funestra.robot_hand import POSITION_MAX, control_limits

from origenerator import motion_engine, osr2
from origenerator.osr2_controls_commands import level_asked_for, max_intensity_asked_for

OSR2_CONTROL_BY_COMMAND = {verb: state for state, verb in OSR2_CONTROL_BUTTONS.items()}

_TRACE_SECONDS = 12.0
REPAINT_MS = 100


def drive_hud(state, active: bool) -> DriveHud:
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
    heights = script.trace(drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    return DriveHud(
        **_bars_drawn(motion.state),
        position=round(POSITION_MAX * (heights[0] if heights else 0.0)),
        driven=DRIVEN_BY_FUNSCRIPT, trace_seconds=_TRACE_SECONDS, waveform=heights)


def _bars_drawn(bars) -> dict:
    return dict(speed=bars.speed, amplitude=bars.amplitude, center=bars.center,
                shape=bars.shape.value, max_intensity=bars.max_intensity,
                **asdict(control_limits(bars)))


@dataclass(frozen=True)
class Osr2Situation:
    device: Osr2Mode = Osr2Mode.CONTROLLED
    trouble: Osr2Trouble | None = None
    control: str = OSR2_CONTROL_UNANSWERED
    script: object = None
    broker_running: bool = True


USUAL_SITUATION = Osr2Situation()


def osr2_controls_hud(motion, situation: Osr2Situation = USUAL_SITUATION) -> MainHud:
    shown = osr2_controls_state(motion, situation)
    return MainHud(
        main_hud_model=MainHudModel(
            main_mode=MainMode.GENAU,
            osr2=shown.osr2, osr2_control=situation.control, paused=shown.paused,
            osr2_rows=shown.osr2_rows, osr2_controls=shown.osr2_controls,
            max_intensity=shown.max_intensity,
        ),
        drive=shown.drive,
    )


@dataclass(frozen=True)
class Osr2ControlsState:
    osr2_rows: tuple
    osr2: str
    osr2_control: str
    drive: DriveHud
    max_intensity: int
    paused: bool = False
    osr2_controls: tuple = ()


def osr2_controls_state(motion, situation: Osr2Situation = USUAL_SITUATION) -> Osr2ControlsState:
    device, trouble, control = situation.device, situation.trouble, situation.control
    script, broker_running = situation.script, situation.broker_running
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
    return MainHudPainter(device_only=True).rgba(osr2_controls_hud(driving, Osr2Situation(control=OSR2_DRIVING)))[1]


def post_device_action(action: str, *, motion, control=None) -> bool:
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
    if control is not None:
        control.set_state(state)
    elif state == OSR2_DRIVING:
        motion.release()
    elif state == OSR2_PARKED:
        motion.hold(OSR2_PARKED)
