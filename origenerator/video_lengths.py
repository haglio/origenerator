from __future__ import annotations

from origenerator import gallery
from origenerator.generation_state import GenerationStatus
from origenerator.media import MediaType, VideoHeader, video_header
from origenerator.output_places import OutputPlaces


def video_length_of(row: dict, places: OutputPlaces) -> VideoHeader | None:
    if gallery.media_type_of_row(row) != MediaType.VIDEO:
        return None
    video = gallery.video_file_of(row, places)
    return video_header(video) if video is not None else None


def as_recorded(length: VideoHeader) -> dict:
    return {"video_seconds": length.seconds, "video_frames": round(length.frames)}


def _unmeasured(row: dict) -> bool:
    return row.get("video_seconds") is None or (
        row.get("video_frames") is None and gallery.is_a_flick(row))


def record_video_lengths(db, places: OutputPlaces) -> int:
    measured = {row["prompt_id"]: (row, as_recorded(length)) for row in db.list_generations()
                if row["status"] == GenerationStatus.COMPLETED and _unmeasured(row)
                and (length := video_length_of(row, places)) is not None}
    for column in ("video_seconds", "video_frames"):
        db.fill_in(column, {prompt_id: found[column] for prompt_id, (row, found) in measured.items()
                            if row.get(column) is None})
    return len(measured)
