from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app_support.mirrored_tree import record_path

from origenerator import outside_videos
from origenerator.db_generations import library_paths_in
from origenerator.generation_state import GenerationSource, source_of
from origenerator.outside_journal import actions_in, said_in
from origenerator.sent_back import SentBack, send_back

PlacesHere = Callable[[], outside_videos.Places | None]


def strike(db, slide, places_here: PlacesHere, sent_back: SentBack) -> str:
    row = db.get_generation(slide.prompt_id) or {}
    said = send_back(db, slide.prompt_id, sent_back)
    places = places_here()
    if said and _a_pick_still_waits(row, places):
        outside_videos.cancel_picks(places, row)
    return said


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
