"""How a press on the Funestras' console or a slideshow's HUD is spelled.

The console painter and the satellite HUD hand their presses back as bare
strings, and three surfaces here decode them: the console under Core and under a fullscreen slideshow
(:func:`~origenerator.gui.console.post_device_action`), a slideshow's own HUD
(:mod:`origenerator.gui.slideshow_hud`), and the channel a Fun Time session drives
a hosted slideshow through (:mod:`origenerator.fun_time_bridge`).  Each used to
hold its own slice index and its own way of gluing a side's name onto a verb,
so the spelling lived in three places and matched by coincidence.

Nothing here knows Qt, and nothing here decides what a press *does* -- that is
:func:`~origenerator.slideshow_buttons.answer` for a slideshow and
:func:`~origenerator.gui.console.post_device_action` for the device.  This
says only what a press IS.
"""

from __future__ import annotations

from typing import NamedTuple

from funestra import drive_layout

#: The prefix every Robot Hand verb carries.  `tests/test_console_commands.py`
#: holds it against the presses funestra itself builds, so a spelling
#: changed there turns a test red instead of arriving as an unknown press.
ROBOT_HAND = "robot_hand_"

#: The three axes a band sets outright, read off the module that draws them.
AXES = (drive_layout.AMPLITUDE, drive_layout.CENTER, drive_layout.SPEED)


class Level(NamedTuple):
    """The axis a press set and what it set it to: ``robot_hand_amp_57``."""

    axis: str
    value: int


def level_asked_for(action: str) -> Level | None:
    """*action* as the level it sets, or ``None`` for any other press."""
    if not action.startswith(ROBOT_HAND):
        return None
    axis, _, value = action.removeprefix(ROBOT_HAND).rpartition("_")
    if axis in AXES and value.isdigit():
        return Level(axis, int(value))
    return None


def max_intensity_asked_for(action: str) -> int | None:
    value = action.removeprefix(f"{drive_layout.MAX_INTENSITY}_")
    if value != action and value.isdigit():
        return int(value)
    return None


#: The one press spelled the other way round, with the side in the middle and
#: the row it names as its payload: ``filter_<side>_<row>``.
FILTER = "filter"


def side_press(side: str, verb: str, argument: str = "") -> tuple[str, str]:
    """A press as the HUD spells it, taken apart into what it asks and what
    it carries: ``<side>_<action>`` and its ``|`` payload for most, and
    :data:`FILTER`'s row for the one spelled the other way round."""
    filtering = spelled_filter(side, "")
    if verb.startswith(filtering):
        return FILTER, verb[len(filtering):]
    return verb.removeprefix(f"{side}_"), argument


def spelled_for(side: str, action: str) -> str:
    """How *side*'s HUD spells *action* -- what :func:`side_press` undoes."""
    return f"{side}_{action}"


def spelled_filter(side: str, row: str) -> str:
    """How *side*'s HUD spells narrowing to *row* -- what :func:`side_press` undoes."""
    return f"{FILTER}_{side}_{row}"


def side_spoken_to(keyword: str, sides) -> str | None:
    """Which of *sides* a verb is said to, or ``None`` for none of them.

    Case-blind, because a session sends its verbs folded
    (``PORTRAIT_NEXT``) where a HUD posts them as it drew them.
    """
    folded = keyword.casefold()
    for side in sides:
        if folded.startswith((spelled_for(side, ""), spelled_filter(side, ""))):
            return side
    return None
