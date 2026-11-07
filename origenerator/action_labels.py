from __future__ import annotations

import json
from typing import NamedTuple

from origenerator.media import MediaType


class Labels(NamedTuple):
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


def labels_of(row: dict, side: str) -> Labels:
    actions, checked = columns(side)
    return Labels(_names_in(row.get(actions)), _names_in(row.get(checked)))


def is_labeled(row: dict, side: str) -> bool:
    return row.get(columns(side)[0]) is not None


def stored(labels: Labels) -> tuple[str, str]:
    return json.dumps(list(labels.actions)), json.dumps(list(labels.checked))


def combined_actions(*labels: Labels) -> tuple[str, ...]:
    return tuple(dict.fromkeys(action for each in labels for action in each.actions))
