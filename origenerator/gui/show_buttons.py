"""The buttons Origenerator declares on a show's HUD.

A show wears the players' own panel (:mod:`origenerator.gui.show_hud`), and a
panel's buttons are its source's to declare: rows of
:class:`player_core.hud_button.Button`, each carrying the verb a press posts.
The verbs are the side's own, spelled the way a satellite's are — hosted, the
session routes ``portrait_next`` back to whatever holds that side; standalone,
the show answers the same verb itself.

Only what a show answers is declared.  A hosted show has no window of its own
to park, so the panel offers the mode pair in place of minimize: a button drawn
for sameness whose press is swallowed says a feature is there when it is not.
"""
from __future__ import annotations

from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core.hud_button import FIT_THE_WORD, Button  # noqa: E402
from player_core.hud_marks import FMODE_ICON, MINIMIZE_ICON, shared_mark  # noqa: E402
from player_core.hud_status import F_MODE_LABEL  # noqa: E402

# The band, in the order the players put the same controls in: step either way,
# then the three about the item on screen, then what narrows the set and the way
# back out of all of it.  The tuples are the groups the wider gap opens between.
CONTROL_GROUPS = (
    ("prev", "next"),
    ("lock", "trash", "fmode"),
    ("enhanced", "reset"),
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
    "minimize": MINIMIZE_ICON,
}

# What each one is, in this app's words rather than a player's: these act on the
# generations this app made, so the bin is the toolbar's Delete and the hold is
# the whole of what holding a slide means here.
CONTROL_TOOLTIPS = {
    "prev": "Previous slide",
    "next": "Next slide",
    "lock": "Hold this one on screen — starring it, and asking for a better version",
    "trash": "Delete this one and move on",
    "fmode": f"{F_MODE_LABEL} — play only the favorites",
    "enhanced": "Enhanced only — play just the pictures that have been enhanced",
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


def show_rows(side: str, *, locked: bool = False, f_mode: bool = False,
              enhanced: bool = False, hosted: bool = False,
              ) -> tuple[tuple[Button, ...], ...]:
    """The rows a show's HUD draws: the session's mode pair where one hosts this
    show, then the show's own band."""
    names = [name for group in CONTROL_GROUPS for name in group
             if not (hosted and name == "minimize")]
    lit = {"lock": locked, "fmode": f_mode, "enhanced": enhanced}
    band = tuple(
        _control(side, name, hosted=hosted, lit=lit.get(name, False),
                 group_break=index > 0 and _GROUP_OF[name] != _GROUP_OF[names[index - 1]])
        for index, name in enumerate(names)
    )
    return (_mode_row(), band) if hosted else (band,)


def _mode_row() -> tuple[Button, ...]:
    return tuple(
        Button(action, label, MODE_TOOLTIPS[action], width=FIT_THE_WORD, lit=lit)
        for action, label, lit in MODE_BUTTONS
    )


def _control(side: str, name: str, *, hosted: bool, lit: bool, group_break: bool) -> Button:
    tooltip = RESET_TOOLTIPS[hosted] if name == "reset" else CONTROL_TOOLTIPS[name]
    return Button(f"{side}_{name}", CONTROL_FACES[name], tooltip, lit=lit,
                  favorite=name in ("lock", "fmode"), enhanced=name == "enhanced",
                  danger=name == "trash", group_break=group_break)
