"""The buttons Origenerator declares on a slideshow's HUD.

A slideshow wears the Funestras' own HUD (:mod:`origenerator.gui.slideshow_hud`), and a
HUD's buttons are its source's to declare: rows of
:class:`funestra.hud_button.Button`, each carrying the verb a press posts.
The verbs are the side's own, spelled the way a satellite's are — hosted, the
session routes ``portrait_next`` back to whatever holds that side; standalone,
the slideshow answers the same verb itself.

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
from funestra.hud_button import FIT_THE_WORD, Button
from funestra.hud_marks import FMODE_ICON, LOCK_ICON, NEXT_ICON, PREVIOUS_ICON, shared_mark
from funestra.hud_overlay import FOOT_DRAG, FOOT_PRESS, FOOT_RELEASE, FOOT_WHEEL
from funestra.hud_title import F_MODE_LABEL, LATEST_LABEL, SHUFFLE_LABEL

from origenerator.osr2_controls_commands import FILTER, spelled_for

# The HUD's button row, in the order the Funestras put the same controls in.  The tuples are
# the groups the wider gap opens between.
CONTROL_GROUPS = (
    ("prev", "next"),
    ("lock", "trash", "fmode"),
    ("enhanced", "reset"),
    ("shuffle", "latest"),
    ("cycle_version",),
)
_GROUP_OF = {name: index for index, group in enumerate(CONTROL_GROUPS) for name in group}

# The mode pair, which is about the SESSION rather than about this slideshow: the way
# back to the Funestras' own videos, and this mode lit beside it.  Its verbs are
# the session's dashboard commands, posted verbatim.
#: The verb that asks the session to show this app, which is the way to
#: anything of this app's while a session is running the room.
ORIGENERATOR_MODE = "origenerator_activate"


def origenerator_mode_on(side: str) -> str:
    return spelled_for(side, ORIGENERATOR_MODE)

MODE_BUTTONS = (
    ("satellites_kino_activate", "Kino", False),
    (ORIGENERATOR_MODE, "Origenerator", True),
)
MODE_TOOLTIPS = {
    "satellites_kino_activate": "Kino mode — the Satellite Funestras and the Random Favs Browser",
    "origenerator_activate":
        "Origenerator mode — Origenerator over the browser, its slideshows over the Funestras",
}

CONTROL_FACES = {
    "prev": PREVIOUS_ICON, "next": NEXT_ICON, "lock": LOCK_ICON,
    "trash": shared_mark("trash"), "fmode": FMODE_ICON,
    "enhanced": shared_mark("enhance_filter"), "reset": shared_mark("reset"),
    "shuffle": shared_mark("shuffle"), "latest": shared_mark("latest"),
    "cycle_version": shared_mark("versions"),
}

# Said after the versions tooltip on an item filed once, so a faded button says
# what is missing rather than looking broken.
_NO_OTHER_VERSION = " (none for this one)"

# What each one is, in this app's words rather than a Funestra's: these act on the
# generations this app made, so the Trash is the Gallery pane buttons' Delete and the lock is
# the whole of what locking a slide means here.
CONTROL_TOOLTIPS = {
    "prev": "Previous slide",
    "next": "Next slide",
    "lock": "Lock this one on screen — favoriting it, and asking for a better version",
    "trash": "Delete this one and move on",
    "fmode": f"{F_MODE_LABEL} — play only the favorites",
    "enhanced": "Enhanced only — play just the images that have been enhanced",
    "shuffle": f"{SHUFFLE_LABEL} — every image and video of this shape, shuffled",
    "latest": f"{LATEST_LABEL} — every image and video of this shape, newest first",
    "cycle_version": "Other versions of this one — an enhancement, the image it was "
                "made from, the upscale Evolver made of a video",
}
# Reset means what the side goes back TO, which is not the same in both places:
# hosted it is the region's base state — that side's whole library, the way a
# Funestra's reset leaves it browsing its own — and standalone there is no such
# state, so it is this slideshow's own set from the top.
RESET_TOOLTIPS = {
    True: "Reset — this side's whole library back, with both filters off",
    False: "Reset — both filters off, and this set from the top",
}


def slideshow_rows(side: str, *, locked: bool = False, favorites_filter: bool = False,
                   enhanced: bool = False, order: str = "", hosted: bool = False,
                   own_window: bool = True, has_other_versions: bool = False,
                   clip_seconds: int | None = None) -> tuple[tuple[Button, ...], ...]:
    """The rows a slideshow's HUD draws, for the surface it is drawn on.

    *own_window* is whether this slideshow has a window of this app's.  Handed to
    one of a session's Funestras there is none, and the mode pair is the
    session's own to put on its HUD; in a window over a session's region the
    slideshow draws that pair itself.
    """
    mode_row = hosted and own_window
    names = [name for group in CONTROL_GROUPS for name in group]
    lit = {"lock": locked, "fmode": favorites_filter, "enhanced": enhanced,
           "shuffle": order == SHUFFLE_LABEL, "latest": order == LATEST_LABEL}
    row = tuple(
        _control(side, name, hosted=hosted, lit=lit.get(name, False),
                 dim=name == "cycle_version" and not has_other_versions,
                 group_break=index > 0 and _GROUP_OF[name] != _GROUP_OF[names[index - 1]])
        for index, name in enumerate(names)
    )
    pace = () if clip_seconds is None else (clip_seconds_row(side, clip_seconds),)
    return (_mode_row(), row, *pace) if mode_row else (row, *pace)


def clip_seconds_row(side: str, seconds: int) -> tuple[Button, ...]:
    return (
        Button("", "Clip seconds", "", width=ROW_LABEL_W),
        Button(f"{side}_clip_seconds_down", shared_mark("minus"), "Move on sooner",
               group_break=True),
        Button("", f"{seconds}s", "", width=VALUE_W),
        Button(f"{side}_clip_seconds_up", shared_mark("plus"), "Leave each clip longer"),
    )


_NEWER, _OLDER = -1, 1

# What each press asks of a slideshow, by the name its verb carries after the side:
# the button row's buttons, the map's own chrome, the session's own keys and a window's
# shifted arrows, all in the Funestras' spelling.
_PRESSES: dict[str, Callable[[Any], object]] = {
    "prev": lambda host: host.slideshow_step(-1),
    "next": lambda host: host.slideshow_step(1),
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
    "lock_action": lambda host: host.slideshow_filter_to_the_act_on_screen(),
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
HUD_CORNER = "hud_corner"
HUD_MINIMIZED = "hud_minimized"
HUD_PLACES: dict[str, str] = {HUD_CORNER: "{corner}", HUD_MINIMIZED: "{on}"}

PRESSES = tuple(_PRESSES)
PRESSES_ABOUT_THE_SLIDE = frozenset({"trash", "lock_action", "seed_loop", "action_loop", "loop",
                                     "cycle_seed", "cycle_action"})
PRESSES_ABOUT_A_FILE = tuple(_PRESSES_ABOUT_A_FILE)
# The Job Queue's block at the HUD's foot, each with where in it the pointer was.
PRESSES_ON_THE_QUEUE = {FOOT_PRESS: "{x}|{y}", FOOT_DRAG: "{x}|{y}", FOOT_RELEASE: "{x}|{y}",
                        FOOT_WHEEL: "{steps}|{x}|{y}"}


def answer(host, action: str, argument: str = "") -> bool:
    """Do what a press on a slideshow's HUD asks of *host*, by the name its verb
    carries after the side ("next", "fmode", "play_video"), and say whether the
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


def _control(side: str, name: str, *, hosted: bool, lit: bool, dim: bool,
             group_break: bool) -> Button:
    tooltip = RESET_TOOLTIPS[hosted] if name == "reset" else CONTROL_TOOLTIPS[name]
    if dim:
        tooltip += _NO_OTHER_VERSION
    return Button(f"{side}_{name}", CONTROL_FACES[name], tooltip, lit=lit, dim=dim,
                  favorite=name in ("lock", "fmode"), enhanced=name == "enhanced",
                  danger=name == "trash", group_break=group_break)
