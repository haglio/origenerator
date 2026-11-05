from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app_support import video_action
from app_support.mirrored_tree import record_path

from origenerator import outside_videos
from origenerator.db_generations import library_paths_in
from origenerator.gallery.output import media_type_of_row
from origenerator.generation_state import GenerationSource, source_of
from origenerator.media import MediaType, media_type_from_filename
from origenerator.outside_journal import actions_in, said_in

PlacesHere = Callable[[], outside_videos.Places | None]


def say(db, prompt_id: str, row: dict, said: str, *, places_here: PlacesHere | None = None) -> None:
    if (_is_a_video(row) and source_of(row) == GenerationSource.OUTSIDE
            and (places := (places_here or outside_videos.places_here)())):
        outside_videos.pick_action(db, places, row, said)
    else:
        _write(db, prompt_id, row, said)


def strike(db, slide, places_here: PlacesHere) -> str:
    row = db.get_generation(slide.prompt_id) or {}
    said = _said_of(row)
    places = places_here()
    if said and _a_pick_still_waits(row, places):
        say(db, slide.prompt_id, row, "", places_here=lambda: places)
    elif said:
        _write(db, slide.prompt_id, row, "")
    recorded = _struck_from_the_record_of(slide.path, places)
    return said or recorded


def _is_a_video(row: dict) -> bool:
    return media_type_of_row(row) == MediaType.VIDEO


def _write(db, prompt_id: str, row: dict, said: str) -> None:
    if _is_a_video(row):
        db.set_action(prompt_id, said or None)
    else:
        db.set_image_state(prompt_id, said or None)


def _said_of(row: dict) -> str:
    return row.get("action" if _is_a_video(row) else "image_state") or ""


def _a_pick_still_waits(row: dict, places: outside_videos.Places | None) -> bool:
    if places is None or source_of(row) != GenerationSource.OUTSIDE:
        return False
    picked = actions_in(said_in(places.journal))
    return any(_waits(picked.get(_place_of(video, places)), video, places)
               for video in map(Path, library_paths_in(row.get("output_files"))))


def _place_of(video: Path, places: outside_videos.Places) -> str:
    return video.relative_to(places.library_root).as_posix()


def _waits(pick: tuple[float, str] | None, video: Path, places: outside_videos.Places) -> bool:
    if pick is None or not pick[1]:
        return False
    record = record_path(video, places.records_folder)
    return record is None or not record.is_file() or pick[0] >= record.stat().st_mtime


def _struck_from_the_record_of(played, places: outside_videos.Places | None) -> str:
    if places is None or media_type_from_filename(str(played)) != MediaType.VIDEO:
        return ""
    record = record_path(Path(played), places.records_folder)
    return "" if record is None else video_action.strike(record)
