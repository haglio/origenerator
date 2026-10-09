"""The pass a show hands a Funestra: each slide as the item the Funestra plays,
turned so the slide on screen leads."""
from __future__ import annotations

from pathlib import Path

from player_core.playlist import PlaylistItem

from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.funscript import funscript_of
from origenerator.media import MediaType


def playlist_item(path, media_type: str) -> PlaylistItem:
    path = Path(str(path))
    if media_type != MediaType.VIDEO:
        return PlaylistItem(path)
    return PlaylistItem(path, funscript_of(path, output_dir=COMFYUI_OUTPUT_DIR))


def slide_item(slide) -> PlaylistItem:
    return playlist_item(slide.path, slide.media_type)


def rotated_onto(items: list, current) -> list:
    """*items* turned so *current* leads, leaving the order otherwise alone."""
    if current is None:
        return items
    for index, item in enumerate(items):
        if item is current or (item.prompt_id is not None
                               and item.prompt_id == current.prompt_id):
            return items[index:] + items[:index]
    return items
