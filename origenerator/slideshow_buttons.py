"""The buttons Origenerator declares on a slideshow's HUD.

A slideshow wears the Funestras' own HUD (:mod:`origenerator.gui.slideshow_hud`), and a
HUD's buttons are its source's to declare: rows of
:class:`funestra.hud_button.Button`, each carrying the verb a press posts.
The verbs are the side's own, spelled the way a satellite's are — hosted, the
session routes ``portrait_next`` back to whatever holds that shape; standalone,
the slideshow answers the same verb itself.

The controls a Satellite's HUD carries in Kino mode too are
:mod:`funestra.hud_controls`' declarations, in that HUD's order; this app adds
its own words where a control means something else here (reset), and the two controls only a slideshow has (Enhanced only, Clip seconds).

Only what a slideshow answers is declared, which depends on what is drawing the
HUD: the session's mode pair is drawn by a slideshow covering a region — but
not by one handed to a Funestra, whose HUD the session puts its own row on.  A
button drawn for sameness whose press is swallowed says a feature is there when
it is not.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from funestra.console import ROW_LABEL_W, VALUE_W
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
from funestra.hud_marks import shared_mark
from funestra.hud_overlay import FOOT_DRAG, FOOT_PRESS, FOOT_RELEASE, FOOT_WHEEL
from funestra.hud_title import LATEST_LABEL

from origenerator.osr2_controls_commands import FILTER, spelled_for

# What a slideshow plays, in the word its HUD says.
SLIDE = "slide"

# The mode pair, which is about the SESSION rather than about this slideshow: the way
# back to the Funestras' own videos, and this mode lit beside it.  Its verbs are
# the session's dashboard commands, posted verbatim.
#: The verb that asks the session to show this app, which is the way to
#: anything of this app's while a session is running the room.
ORIGENERATOR_MODE = "origenerator_activate"


def origenerator_mode_on(shape: str) -> str:
    return spelled_for(shape, ORIGENERATOR_MODE)

MODE_BUTTONS = (
    ("satellites_kino_activate", "Kino", False),
    (ORIGENERATOR_MODE, "Origenerator", True),
)
MODE_TOOLTIPS = {
    "satellites_kino_activate": "Kino mode — the Satellite Funestras and the Random Favs Browser",
    "origenerator_activate":
        "Origenerator mode — Origenerator over the browser, its slideshows over the Funestras",
}

ENHANCED_ICON = shared_mark("enhance_filter")

ENHANCED_TOOLTIP = "Enhanced only — play just the images that have been enhanced"
# Reset means what the shape goes back TO, which is not the same in both places:
# hosted it is the region's base state — that side's whole library, the way a
# Funestra's reset leaves it browsing its own — and standalone there is no such
# state, so it is this slideshow's own set from the top.
RESET_TOOLTIPS = {
    True: "Reset — this side's whole library back, with both filters off",
    False: "Reset — both filters off, and this set from the top",
}


def slideshow_rows(shape: str, *, locked: bool = False, favorites_filter: bool = False,
                   enhanced: bool = False, order: str = "", hosted: bool = False,
                   own_window: bool = True, has_other_versions: bool = False,
                   clip_seconds: int | None = None, longer_than_a_step: bool = False,
                   image: bool = False, has_funscript: bool = False, has_osr2: bool = False,
                   nothing_to_reset: bool = False) -> tuple[tuple[Button, ...], ...]:
    """The rows a slideshow's HUD draws, for the surface it is drawn on.

    *own_window* is whether this slideshow has a window of this app's.  Handed to
    one of a session's Funestras there is none, and the mode pair is the
    session's own to put on its HUD; in a window over a session's region the
    slideshow draws that pair itself.
    """
    mode_row = hosted and own_window
    band = (
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
        Button(f"{shape}_clip_seconds_down", shared_mark("minus"), "Move on sooner",
               group_break=True),
        Button("", f"{seconds}s", "", width=VALUE_W),
        Button(f"{shape}_clip_seconds_up", shared_mark("plus"), "Leave each clip longer"),
    )


_NEWER, _OLDER = -1, 1

# What each press asks of a slideshow, by the name its verb carries after the shape:
# the button row's buttons, the map's own chrome, the session's own keys and a window's
# shifted arrows, all in the Funestras' spelling.
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
# The map's thumbnails, whose presses carry the item they were made on.
_PRESSES_ABOUT_A_FILE: dict[str, Callable[[Any, str], object]] = {
    "play_video": lambda host, path: host.show_item(path, lock=False),
    "lock_video": lambda host, path: host.show_item(path, lock=True),
}
# What a session tells a side's HUD about itself: where it sits, whether it
# is parked in its corner, and whether that Funestra has the OSR2, which only
# the session knows and the band's Skip ahead grays by.
HUD_CORNER = "hud_corner"
HUD_MINIMIZED = "hud_minimized"
HAS_THE_OSR2 = "osr2"
HUD_FACTS: dict[str, str] = {HUD_CORNER: "{corner}", HUD_MINIMIZED: "{on}", HAS_THE_OSR2: "{has}"}

PRESSES = tuple(_PRESSES)
PRESSES_ABOUT_THE_SLIDE = frozenset({"trash", "lock_action", "seed_loop", "action_loop", "loop",
                                     "cycle_seed", "cycle_action"})
PRESSES_ABOUT_A_FILE = tuple(_PRESSES_ABOUT_A_FILE)
# The Job Queue's block at the HUD's foot, each with where in it the pointer was.
PRESSES_ON_THE_QUEUE = {FOOT_PRESS: "{x}|{y}", FOOT_DRAG: "{x}|{y}", FOOT_RELEASE: "{x}|{y}",
                        FOOT_WHEEL: "{steps}|{x}|{y}"}


def answer(host, action: str, argument: str = "") -> bool:
    """Do what a press on a slideshow's HUD asks of *host*, by the name its verb
    carries after the shape ("next", "fmode", "play_video"), and say whether the
    slideshow had an answer.

    One table for every way a press reaches a slideshow — its own window's HUD
    and shifted arrows, a session routing a Funestra's HUD back here, and the
    session's own keys — so a button means the same thing whichever of them drew
    it.  ``False`` for minimize, which is a window's rather than a slideshow's, and
    for the Funestras' chrome about acts, which a slideshow has no counterpart for.
    """
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
        Button(action, label, MODE_TOOLTIPS[action], width=FIT_THE_WORD, lit=lit)
        for action, label, lit in MODE_BUTTONS
    )
