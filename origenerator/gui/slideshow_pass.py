"""The pass a slideshow hands a Funestra: each slide as the item the Funestra plays,
turned so the slide on screen leads."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from funestra.playlist import PlaylistItem

from origenerator.config import OUTPUT_PLACES
from origenerator.funscript import funscript_of
from origenerator.media import MediaType


def playlist_item(path, media_type: str, points_of_interest: tuple = (), *,
                  scripts: Mapping = MappingProxyType({})) -> PlaylistItem:
    path = Path(str(path))
    if media_type != MediaType.VIDEO:
        return PlaylistItem(path, points_of_interest=points_of_interest)
    if str(path) in scripts:
        return PlaylistItem(path, scripts[str(path)])
    return PlaylistItem(path, funscript_of(path, places=OUTPUT_PLACES))


def slide_item(slide, points_of_interest: tuple = (), *,
               scripts: Mapping = MappingProxyType({})) -> PlaylistItem:
    return playlist_item(slide.path, slide.media_type, points_of_interest, scripts=scripts)


def rotated_onto(items: list, current) -> list:
    """*items* turned so *current* leads, leaving the order otherwise alone."""
    if current is None:
        return items
    for index, item in enumerate(items):
        if item is current or (item.prompt_id is not None
                               and item.prompt_id == current.prompt_id):
            return items[index:] + items[:index]
    return items
