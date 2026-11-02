from __future__ import annotations

from typing import NamedTuple

from funestra import drive_layout

ROBOT_HAND = "robot_hand_"

AXES = (drive_layout.AMPLITUDE, drive_layout.CENTER, drive_layout.SPEED)


class Level(NamedTuple):
    axis: str
    value: int


def level_asked_for(action: str) -> Level | None:
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


FILTER = "filter"


def shape_press(shape: str, verb: str, argument: str = "") -> tuple[str, str]:
    filtering = spelled_filter(shape, "")
    if verb.startswith(filtering):
        return FILTER, verb[len(filtering):]
    return verb.removeprefix(f"{shape}_"), argument


def spelled_for(shape: str, action: str) -> str:
    return f"{shape}_{action}"


def spelled_filter(shape: str, row: str) -> str:
    return f"{FILTER}_{shape}_{row}"


def shape_spoken_to(keyword: str, shapes) -> str | None:
    folded = keyword.casefold()
    for shape in shapes:
        if folded.startswith((spelled_for(shape, ""), spelled_filter(shape, ""))):
            return shape
    return None
