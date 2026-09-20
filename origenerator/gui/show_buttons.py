"""The buttons Origenerator declares on a show's HUD.

A show wears the players' own panel (:mod:`origenerator.gui.show_hud`), and a
panel's buttons are its source's to declare: rows of
:class:`player_core.hud_button.Button`, each carrying the verb a press posts.
The verbs are the side's own, spelled the way a satellite's are — hosted, the
session routes ``portrait_next`` back to whatever holds that side; standalone,
the show answers the same verb itself.

Only what a show answers is declared, which depends on what is drawing the
panel: minimize parks a window of this app's, so it is offered only where the
show has one, and the session's mode pair is drawn by a show covering a
region — but not by one handed to a player, whose panel the session puts its
own row on.  A button drawn for sameness whose press is swallowed says a
feature is there when it is not.
"""
from __future__ import annotations

from player_core.hud_button import FIT_THE_WORD, Button
from player_core.hud_marks import FMODE_ICON, MINIMIZE_ICON, shared_mark
from player_core.hud_status import F_MODE_LABEL, LATEST_LABEL, SHUFFLE_LABEL

# The band, in the order the players put the same controls in.  The tuples are
# the groups the wider gap opens between.
CONTROL_GROUPS = (
    ("prev", "next"),
    ("lock", "trash", "fmode"),
    ("enhanced", "reset"),
    ("shuffle", "latest"),
    ("cycle_version",),
    ("minimize",),
)
_GROUP_OF = {name: index for index, group in enumerate(CONTROL_GROUPS) for name in group}

# The mode pair, which is about the SESSION rather than about this show: the way
# back to the players' own videos, and this mode lit beside it.  Its verbs are
# the session's dashboard commands, posted verbatim.
MODE_BUTTONS = (
    ("satellites_video_activate", "Video", False),
    ("origenerator_activate", "Origenerator", True),
)
MODE_TOOLTIPS = {
    "satellites_video_activate": "Video mode — the satellite players and the Random Favs Browser",
    "origenerator_activate":
        "Origenerator mode — Origenerator over the browser, its shows over the players",
}

CONTROL_FACES = {
    "prev": "⏮", "next": "⏭", "lock": "🔒",
    "trash": shared_mark("trash"), "fmode": FMODE_ICON,
    "enhanced": shared_mark("enhance_filter"), "reset": shared_mark("reset"),
    "shuffle": shared_mark("shuffle"), "latest": shared_mark("latest"),
    "cycle_version": shared_mark("versions"), "minimize": MINIMIZE_ICON,
}

# Said after the versions tooltip on an item filed once, so a faded button says
# what is missing rather than looking broken.
_NO_OTHER_VERSION = " (none for this one)"

# What each one is, in this app's words rather than a player's: these act on the
# generations this app made, so the bin is the toolbar's Delete and the hold is
# the whole of what holding a slide means here.
CONTROL_TOOLTIPS = {
    "prev": "Previous slide",
    "next": "Next slide",
    "lock": "Hold this one on screen — favoriting it, and asking for a better version",
    "trash": "Delete this one and move on",
    "fmode": f"{F_MODE_LABEL} — play only the favorites",
    "enhanced": "Enhanced only — play just the pictures that have been enhanced",
    "shuffle": f"{SHUFFLE_LABEL} — every picture and video of this shape, shuffled",
    "latest": f"{LATEST_LABEL} — every picture and video of this shape, newest first",
    "cycle_version": "Other versions of this one — an enhancement, the picture it was "
                "made from, the upscale Evolver made of a video",
    "minimize": "Minimize this show — bring it back from the taskbar",
}
# Reset means what the side goes back TO, which is not the same in both places:
# hosted it is the region's base state — that side's whole library, the way a
# player's reset leaves it browsing its own — and standalone there is no such
# state, so it is this show's own set from the top.
RESET_TOOLTIPS = {
    True: "Reset — this side's whole library back, with both filters off",
    False: "Reset — both filters off, and this set from the top",
}


def show_rows(side: str, *, locked: bool = False, favorites_filter: bool = False,
              enhanced: bool = False, order: str = "", hosted: bool = False,
              own_window: bool = True,
              has_other_versions: bool = False) -> tuple[tuple[Button, ...], ...]:
    """The rows a show's HUD draws, for the surface it is drawn on.

    *own_window* is whether this show has a window of this app's — which is
    what minimize parks, and so what decides whether it is offered at all.
    Handed to one of a session's players there is none, and the mode pair is
    the session's own to put on its panel; in a window over a session's region
    the show draws that pair itself.
    """
    mode_row = hosted and own_window
    minimize = own_window and not hosted
    names = [name for group in CONTROL_GROUPS for name in group
             if minimize or name != "minimize"]
    lit = {"lock": locked, "fmode": favorites_filter, "enhanced": enhanced,
           "shuffle": order == SHUFFLE_LABEL, "latest": order == LATEST_LABEL}
    band = tuple(
        _control(side, name, hosted=hosted, lit=lit.get(name, False),
                 dim=name == "cycle_version" and not has_other_versions,
                 group_break=index > 0 and _GROUP_OF[name] != _GROUP_OF[names[index - 1]])
        for index, name in enumerate(names)
    )
    return (_mode_row(), band) if mode_row else (band,)


# The map's own chrome and the session's own keys, in the players' spelling,
# each with the axis or the direction it means on a show.
_LOOPS = {"seed_loop": "seed", "action_loop": "action", "no_loop": ""}
_NAV = {"nav_left": "left", "nav_right": "right", "nav_up": "up", "nav_down": "down",
        # The players' spoken "next seed" / "next action": one step along the
        # row, one step down the column.
        "cycle_seed": "right", "cycle_action": "down"}


def answer(host, action: str, argument: str = "") -> bool:
    """Do what a press on a show's panel asks of *host*, by the name its verb
    carries after the side ("next", "fmode", "play_video"), and say whether the
    show had an answer.

    One table for every way a press reaches a show — its own window's panel,
    a session routing a player's panel back here, and the session's own keys
    — so a button means the same thing whichever of them drew it.  ``False``
    for minimize, which is a window's rather than a show's, and for the
    players' chrome about acts, which a show has no counterpart for.
    """
    if action in ("prev", "next"):
        host.show_step(-1 if action == "prev" else 1)
    elif action == "lock":
        host.show_toggle_hold()
    elif action == "trash":
        host.show_cull()
    elif action == "reset":
        host.show_reset()
    elif action in ("shuffle", "latest"):
        host.show_order(latest=action == "latest")
    elif action == "fmode":
        host.toggle_favorites_filter()
    elif action == "enhanced":
        host.toggle_enhanced_mode()
    elif action in _LOOPS:
        host.show_loop(_LOOPS[action])
    elif action == "loop":
        host.show_loop_cycle()
    elif action == "more_seeds":
        host.show_more_seeds()
    elif action == "filter":
        # The button at the head of a map row, and the session's spoken
        # acts: narrow to that act, the way a satellite's does.
        host.show_filter(argument)
    elif action == "no_filter":
        # A press on the row the filter already is.  Said to a show, "no
        # filter" is the way out of every narrowing, and a hosted panel's
        # press arrives as those very words -- so the press means that here.
        host.clear_modes()
    elif action in _NAV:
        host.show_nav(_NAV[action])
    elif action in ("cycle_version", "cycle_version_back"):
        host.show_step_version(-1 if action.endswith("_back") else 1)
    elif action in ("play_video", "lock_video"):
        # A thumbnail on the map: a click plays it, a double-click holds it.
        host.show_item(argument, hold=action == "lock_video")
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
