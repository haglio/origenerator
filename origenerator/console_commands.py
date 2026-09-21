"""How a press on the players' console or a show's panel is spelled.

The console painter and the satellite HUD hand their presses back as bare
strings, and three surfaces here decode them: the console under the main
window and under a fullscreen show
(:func:`~origenerator.gui.console.post_console_action`), a show's own panel
(:mod:`origenerator.gui.show_hud`), and the channel a Fun Time session drives
a hosted show through (:mod:`origenerator.fun_time_bridge`).  Each used to
hold its own slice index and its own way of gluing a side's name onto a verb,
so the spelling lived in three places and matched by coincidence.

Nothing here knows Qt, and nothing here decides what a press *does* -- that is
:func:`~origenerator.show_buttons.answer` for a show and
:func:`~origenerator.gui.console.post_console_action` for the device.  This
says only what a press IS.
"""

from __future__ import annotations

from typing import NamedTuple

from player_core import drive_layout

#: The prefix every Robot Hand verb carries.  `tests/test_console_commands.py`
#: holds it against the presses player_core itself builds, so a spelling
#: changed there turns a test red instead of arriving as an unknown press.
ROBOT_HAND = "robot_hand_"

#: The three axes a band sets outright, read off the module that draws them.
AXES = (drive_layout.AMPLITUDE, drive_layout.CENTER, drive_layout.SPEED)


class Level(NamedTuple):
    """The axis a press set and what it set it to: ``robot_hand_amp_57``."""

    axis: str
    value: int


def level_asked_for(action: str) -> Level | None:
    """*action* as the level it sets, or ``None`` for any other press.

    The bands post a whole number rather than a step, so this is the one verb
    whose name carries a value; everything else is a word.
    """
    if not action.startswith(ROBOT_HAND):
        return None
    axis, _, value = action.removeprefix(ROBOT_HAND).rpartition("_")
    if axis in AXES and value.isdigit():
        return Level(axis, int(value))
    return None


def side_press(side: str, verb: str, argument: str = "") -> tuple[str, str]:
    """A press as the panel spells it, taken apart into what it asks and what
    it carries: ``<side>_<action>`` and its ``|`` payload for most, and -- the
    one verb spelled the other way round -- ``filter_<side>_<row>``, whose
    payload is the row it names."""
    filtering = f"filter_{side}_"
    if verb.startswith(filtering):
        return "filter", verb[len(filtering):]
    return verb.removeprefix(f"{side}_"), argument


def spelled_for(side: str, action: str) -> str:
    """How *side*'s panel spells *action* -- what :func:`side_press` undoes."""
    return f"{side}_{action}"


def side_spoken_to(keyword: str, sides) -> str | None:
    """Which of *sides* a verb is said to, or ``None`` for none of them.

    Case-blind, because a session sends its verbs folded
    (``PORTRAIT_NEXT``) where a panel posts them as it drew them.
    """
    folded = keyword.casefold()
    for side in sides:
        if folded.startswith((f"{side}_", f"filter_{side}_")):
            return side
    return None
