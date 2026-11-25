from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from funestra.playlist import PlaylistItem

from origenerator.config import OUTPUT_PLACES
from origenerator.funscript import funscript_of
from origenerator.media import MediaType
from origenerator.one_look import one_look


def playlist_item(path, media_type: str, points_of_interest: tuple = (), *,
                  scripts: Mapping = MappingProxyType({})) -> PlaylistItem:
    path = Path(str(path))
    if media_type != MediaType.VIDEO:
        return PlaylistItem(path, points_of_interest=points_of_interest)
    if str(path) in scripts:
        return PlaylistItem(path, scripts[str(path)])
    return PlaylistItem(path, funscript_of(path, places=OUTPUT_PLACES))


def playlist_items(entries, *, scripts: Mapping = MappingProxyType({})) -> list[PlaylistItem]:
    with one_look():
        return [playlist_item(path, media_type, points_of_interest, scripts=scripts)
                for path, media_type, points_of_interest in entries]


def rotated_onto(items: list, current) -> list:
    if current is None:
        return items
    for index, item in enumerate(items):
        if item is current or (item.prompt_id is not None
                               and item.prompt_id == current.prompt_id):
            return items[index:] + items[:index]
    return items
