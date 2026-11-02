from __future__ import annotations

from collections.abc import Callable
from typing import Any

from funestra.funestra_verbs import NEXT_FUNSCRIPTED
from funestra.hud_button import FIT_THE_WORD, Button
from funestra.hud_controls import (
    browse_order_buttons,
    favorites_only_tooltip,
    fmode_button,
    funscript_jump_button,
    lock_button,
    lock_tooltip,
    reset_button,
    transport,
    trash_button,
    versions_button,
)
from funestra.hud_icons import shared_icon
from funestra.hud_overlay import FOOT_DRAG, FOOT_PRESS, FOOT_RELEASE, FOOT_WHEEL
from funestra.hud_title import LATEST_LABEL
from funestra.main_hud import ROW_LABEL_W, VALUE_W

from origenerator.osr2_controls_commands import FILTER, spelled_for

SLIDE = "slide"

ORIGENERATOR_MODE = "origenerator_activate"


def origenerator_mode_on(shape: str) -> str:
    return spelled_for(shape, ORIGENERATOR_MODE)

MODE_BUTTONS = (
    ("satellites_kino_activate", "Kino", False),
    (ORIGENERATOR_MODE, "Origenerator", True),
)

ENHANCED_ICON = shared_icon("enhance_filter")

ENHANCED_TOOLTIP = "Enhanced only — play just the images that have been enhanced"
RESET_TOOLTIPS = {
    True: "Reset — this shape's whole library back, with both filters off",
    False: "Reset — both filters off, and this set from the top",
}


def slideshow_rows(shape: str, *, locked: bool = False, favorites_filter: bool = False,
                   enhanced: bool = False, order: str = "", hosted: bool = False,
                   own_window: bool = True, has_other_versions: bool = False,
                   clip_seconds: int | None = None, longer_than_a_step: bool = False,
                   image: bool = False, has_funscript: bool = False, has_osr2: bool = False,
                   nothing_to_reset: bool = False) -> tuple[tuple[Button, ...], ...]:
    mode_row = hosted and own_window
    row = (
        *transport(shape, noun=SLIDE, longer_than_a_step=longer_than_a_step, image=image),
        funscript_jump_button(f"{shape}_funscript_jump", noun=SLIDE, has_osr2=has_osr2,
                              has_funscript=has_funscript),
        lock_button(shape, locked=locked, tooltip=lock_tooltip(locked, SLIDE)),
        trash_button(shape),
        fmode_button(shape, favorites_only_tooltip(), lit=favorites_filter),
        Button(f"{shape}_enhanced", ENHANCED_ICON, ENHANCED_TOOLTIP, lit=enhanced, enhanced=True,
               group_break=True),
        reset_button(shape, nothing_to_reset=nothing_to_reset, tooltip=RESET_TOOLTIPS[hosted],
                     group_break=False),
        *browse_order_buttons(shape, latest=order == LATEST_LABEL),
        versions_button(f"{shape}_cycle_version", noun=SLIDE, has_other_versions=has_other_versions),
    )
    pace = () if clip_seconds is None else (clip_seconds_row(shape, clip_seconds),)
    return (_mode_row(), row, *pace) if mode_row else (row, *pace)


def clip_seconds_row(shape: str, seconds: int) -> tuple[Button, ...]:
    return (
        Button("", "Clip seconds", "", width=ROW_LABEL_W),
        Button(f"{shape}_clip_seconds_down", shared_icon("minus"), "Move on sooner",
               group_break=True),
        Button("", f"{seconds}s", "", width=VALUE_W),
        Button(f"{shape}_clip_seconds_up", shared_icon("plus"), "Leave each clip longer"),
    )


_NEWER, _OLDER = -1, 1

_PRESSES: dict[str, Callable[[Any], object]] = {
    "prev": lambda host: host.slideshow_step(-1),
    "next": lambda host: host.slideshow_step(1),
    "nudge_prev": lambda host: host.transport.nudge(-1),
    "nudge_next": lambda host: host.transport.nudge(1),
    "funscript_jump": lambda host: host.transport.funscript_jump(),
    "next_funscripted": lambda host: host.slideshow_step(1, verb=NEXT_FUNSCRIPTED),
    "lock": lambda host: host.slideshow_toggle_lock(),
    "lock_on": lambda host: host.set_locked(True),
    "lock_off": lambda host: host.set_locked(False),
    "trash": lambda host: host.slideshow_cull(),
    "reset": lambda host: host.slideshow_reset(),
    "shuffle": lambda host: host.slideshow_order(latest=False),
    "latest": lambda host: host.slideshow_order(latest=True),
    "fmode": lambda host: host.toggle_favorites_filter(),
    "fmode_on": lambda host: host.set_favorites_filter(True),
    "fmode_off": lambda host: host.set_favorites_filter(False),
    "enhanced": lambda host: host.toggle_enhanced_mode(),
    "seed_loop": lambda host: host.slideshow_loop("seed"),
    "action_loop": lambda host: host.slideshow_loop("action"),
    "no_loop": lambda host: host.slideshow_loop(""),
    "loop": lambda host: host.slideshow_loop_cycle(),
    "more_seeds": lambda host: host.slideshow_more_seeds(),
    "no_filter": lambda host: host.clear_modes(),
    "lock_action": lambda host: host.slideshow_filter_to_the_action_on_screen(),
    "nav_left": lambda host: host.slideshow_nav("left"),
    "nav_right": lambda host: host.slideshow_nav("right"),
    "nav_up": lambda host: host.slideshow_nav("up"),
    "nav_down": lambda host: host.slideshow_nav("down"),
    "cycle_seed": lambda host: host.slideshow_nav("right"),
    "cycle_action": lambda host: host.slideshow_nav("down"),
    "cycle_version": lambda host: host.slideshow_step_version(_NEWER),
    "cycle_version_back": lambda host: host.slideshow_step_version(_OLDER),
    "clip_seconds_up": lambda host: host.step_dwell(1),
    "clip_seconds_down": lambda host: host.step_dwell(-1),
}
_PRESSES_ABOUT_A_FILE: dict[str, Callable[[Any, str], object]] = {
    "play_video": lambda host, path: host.show_item(path, lock=False),
    "lock_video": lambda host, path: host.show_item(path, lock=True),
}
HUD_CORNER = "hud_corner"
HUD_MINIMIZED = "hud_minimized"
HAS_THE_OSR2 = "osr2"
HUD_FACTS: dict[str, str] = {HUD_CORNER: "{corner}", HUD_MINIMIZED: "{on}", HAS_THE_OSR2: "{has}"}

PRESSES = tuple(_PRESSES)
PRESSES_ABOUT_THE_SLIDE = frozenset({"trash", "lock_action", "seed_loop", "action_loop", "loop",
                                     "cycle_seed", "cycle_action"})
PRESSES_ABOUT_A_FILE = tuple(_PRESSES_ABOUT_A_FILE)
PRESSES_ON_THE_QUEUE = {FOOT_PRESS: "{x}|{y}", FOOT_DRAG: "{x}|{y}", FOOT_RELEASE: "{x}|{y}",
                        FOOT_WHEEL: "{steps}|{x}|{y}"}


def answer(host, action: str, argument: str = "") -> bool:
    if action in _PRESSES:
        _PRESSES[action](host)
    elif action in _PRESSES_ABOUT_A_FILE:
        _PRESSES_ABOUT_A_FILE[action](host, argument)
    elif action in PRESSES_ON_THE_QUEUE:
        host.press_the_queue(action, argument)
    elif action == FILTER:
        host.slideshow_filter(argument)
    else:
        return False
    return True


def _mode_row() -> tuple[Button, ...]:
    return tuple(
        Button(action, label, "", width=FIT_THE_WORD, lit=lit)
        for action, label, lit in MODE_BUTTONS
    )
