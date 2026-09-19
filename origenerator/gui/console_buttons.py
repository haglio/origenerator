"""The buttons this app puts on Genau's console, row by row: Genau's transport,
the pace an unheld slide moves on at, and the motion's own row.  Only what
:class:`origenerator.gui.motion_panel.MotionPanel` answers is declared."""

from __future__ import annotations

from player_core.console import (
    OSR2_CONTROL_OFF,
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
    ROW_LABEL_W,
    VALUE_W,
    shape_label,
)
from player_core.hud_button import Button
from player_core.hud_marks import shared_mark

Rows = tuple[tuple[Button, ...], ...]


def console_rows(*, locked: bool, pace_s: int, control: str, cruise: bool,
                 learned: bool, shape: str) -> Rows:
    return (
        _transport_row(locked=locked, pace_s=pace_s),
        _pace_row(),
        _motion_row(control=control, cruise=cruise, learned=learned, shape=shape),
    )


def _transport_row(*, locked: bool, pace_s: int) -> tuple[Button, ...]:
    return (
        Button("genau_prev_clip", "⏮", "Previous clip"),
        Button("genau_next_clip", "⏭", "Next clip"),
        Button("main_lock", "🔒",
               f"Locked — this clip repeats; press to move on every {pace_s}s" if locked
               else f"Unlocked — moving on every {pace_s}s; press to hold this clip",
               lit=locked, favorite=True, group_break=True),
        Button("genau_weird_clip", shared_mark("trash"), "Mark weird — move it out",
               danger=True, group_break=True),
    )


def _pace_row() -> tuple[Button, ...]:
    return (
        Button("", "Clip seconds", "", width=ROW_LABEL_W),
        Button("genau_clip_seconds_down", "−", "Move on sooner", group_break=True),
        Button("", "", "", width=VALUE_W, host_value="advance_interval"),
        Button("genau_clip_seconds_up", "+", "Leave each clip longer"),
    )


def _motion_row(*, control: str, cruise: bool, learned: bool,
                shape: str) -> tuple[Button, ...]:
    """The motion's shape, then the four states of OSR2 control from off to on.

    Off only where the app answers control at all (*control* empty is a
    console with no switch handed over), since a switch nothing hears is worse
    than no switch.
    """
    return (
        Button("robot_hand_toggle_cruise", "cc",
               "Cruise control: vary the motion hands-free", lit=cruise),
        Button("robot_hand_toggle_learned", "hi",
               "Human inspired: motion drawn from real hand-made scripts, not a waveform",
               lit=learned),
        Button("robot_hand_cycle_shape", shared_mark("wave"),
               f"Waveform: {shape_label(shape)}"),
        Button("quarter_button", shared_mark("quarter_offset"), "Offset the motion a ¼ cycle"),
        *((
            Button("osr2_control_off", shared_mark("control_off"),
                   "Control off — the OSR2 settles home and is left there; "
                   "nothing here moves it again until you park, retract or "
                   "drive it.  The device itself stays on: this is the app "
                   "letting go of it, not the OSR2 switching off",
                   warn=control == OSR2_CONTROL_OFF, group_break=True),
        ) if control else ()),
        Button("robot_hand_park", shared_mark("park"),
               "Parked — the OSR2 held still, settled home",
               lit=control == OSR2_PARKED, group_break=not control),
        Button("robot_hand_retract", shared_mark("retract"),
               "Retracted — the OSR2 held still at the far end, away from you",
               lit=control == OSR2_RETRACTED),
        Button("robot_hand_release", shared_mark("release"),
               "Driving — the OSR2 back on whatever the motion was doing, "
               "cruise included",
               lit=control == OSR2_DRIVING),
    )
