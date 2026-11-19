from __future__ import annotations

from origenerator import gallery
from origenerator.generation_state import GenerationStatus
from origenerator.media import video_header
from origenerator.output_places import OutputPlaces


def video_seconds_of(row: dict, places: OutputPlaces) -> float | None:
    video = gallery.video_file_of(row, places)
    header = video_header(video) if video is not None else None
    return header.seconds if header is not None else None


def record_video_lengths(db, places: OutputPlaces) -> int:
    lengths = {row["prompt_id"]: seconds for row in db.list_generations()
               if row.get("video_seconds") is None
               and row["status"] == GenerationStatus.COMPLETED
               and (seconds := video_seconds_of(row, places)) is not None}
    db.fill_in("video_seconds", lengths)
    return len(lengths)
