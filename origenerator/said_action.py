from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app_support import video_action
from app_support.mirrored_tree import record_path

from origenerator import outside_videos
from origenerator.gallery.output import media_type_of_row
from origenerator.generation_state import GenerationSource, source_of
from origenerator.media import MediaType, media_type_from_filename

PlacesHere = Callable[[], outside_videos.Places | None]


def say(db, prompt_id: str, row: dict, said: str, *, places_here: PlacesHere | None = None) -> None:
    if media_type_of_row(row) != MediaType.VIDEO:
        db.set_image_state(prompt_id, said or None)
    elif (source_of(row) == GenerationSource.OUTSIDE
          and (places := (places_here or outside_videos.places_here)())):
        outside_videos.pick_action(db, places, row, said)
    else:
        db.set_action(prompt_id, said or None)


def strike(db, slide, places_here: PlacesHere) -> str:
    row = db.get_generation(slide.prompt_id) or {}
    said = _said_of(row)
    if said:
        say(db, slide.prompt_id, row, "", places_here=places_here)
    recorded = _struck_from_the_record_of(slide.path, places_here())
    return said or recorded


def _said_of(row: dict) -> str:
    held_as = "action" if media_type_of_row(row) == MediaType.VIDEO else "image_state"
    return row.get(held_as) or ""


def _struck_from_the_record_of(played, places: outside_videos.Places | None) -> str:
    if places is None or media_type_from_filename(str(played)) != MediaType.VIDEO:
        return ""
    record = record_path(Path(played), places.records_folder)
    return "" if record is None else video_action.strike(record)
