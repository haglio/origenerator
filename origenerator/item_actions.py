from __future__ import annotations

import json
from typing import NamedTuple

from origenerator.media import MediaType


class ItemActions(NamedTuple):
    actions: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()


_COLUMNS = {
    MediaType.IMAGE: ("image_actions", "image_checked"),
    MediaType.VIDEO: ("video_actions", "video_checked"),
}


def columns(side: str) -> tuple[str, str]:
    return _COLUMNS[side]


def _names_in(stored_list) -> tuple[str, ...]:
    try:
        listed = json.loads(stored_list) if stored_list else []
    except (TypeError, ValueError):
        return ()
    if not isinstance(listed, list):
        return ()
    return tuple(dict.fromkeys(name for name in listed if isinstance(name, str) and name))


def actions_of(row: dict, side: str) -> ItemActions:
    actions, checked = columns(side)
    return ItemActions(_names_in(row.get(actions)), _names_in(row.get(checked)))


def has_actions(row: dict, side: str) -> bool:
    return row.get(columns(side)[0]) is not None


def actions_if_any(row: dict, side: str) -> ItemActions | None:
    return actions_of(row, side) if has_actions(row, side) else None


def stored(item_actions: ItemActions) -> tuple[str, str]:
    return json.dumps(list(item_actions.actions)), json.dumps(list(item_actions.checked))


def combined_actions(*item_actions: ItemActions) -> tuple[str, ...]:
    return tuple(dict.fromkeys(action for each in item_actions for action in each.actions))
