from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app_support.mirrored_tree import filed_record
from app_support.video_names import video_title

from origenerator import config
from origenerator.db_generations import library_paths_in
from origenerator.evolver_export import PARTIAL_MARKER
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.media import MediaType, media_type_from_filename
from origenerator.one_at_a_time import WAIT_S
from origenerator.outside_videos import (
    VIDEOS_PER_WRITE,
    Made,
    made_at,
    recorded_fields,
    turn_at,
)
from origenerator.thumbnail import generate_animated_thumbnail, generate_thumbnail
from origenerator.workflows.non_ai import (
    FOLDER_KEY,
    FOLDER_PARTS_IN_A_NAME,
    TITLE_KEY,
    NonAiWorkflow,
    non_ai_workflow,
)


@dataclass(frozen=True)
class NonAiPlaces:
    videos: Path
    thumb_dir: Path
    records: Path


def places_here() -> NonAiPlaces:
    return NonAiPlaces(videos=config.NON_AI_DIR, thumb_dir=config.THUMB_DIR,
                       records=config.VIDEO_RECORDS_DIR)


def scan_in_turn(db, places: NonAiPlaces, *, wait_s: float = WAIT_S) -> int:
    with turn_at(db, wait_s=wait_s).taken() as ours:
        return scan(db, places) if ours else 0


def scan(db, places: NonAiPlaces, *, videos_per_write: int = VIDEOS_PER_WRITE) -> int:
    take_up_new_titles(db, places)
    held = db.library_paths() | db.trashed_library_paths()
    new = (video for video in non_ai_videos(places.videos) if str(video) not in held)
    brought_in = 0
    for batch in itertools.batched((row_bringing_in(video, places) for video in new),
                                   videos_per_write):
        db.insert_rows(list(batch))
        brought_in += len(batch)
    return brought_in


def take_up_new_titles(db, places: NonAiPlaces) -> None:
    for row in db.list_generations():
        if row["source"] != GenerationSource.NON_AI:
            continue
        params = json.loads(row["params_json"])
        for video in library_paths_in(row["output_files"]):
            title = title_of(Path(video), places)
            if params.get(TITLE_KEY) != title:
                db.set_params_json(row["prompt_id"], json.dumps({**params, TITLE_KEY: title}))


def non_ai_videos(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*")
                  if path.is_file() and PARTIAL_MARKER not in path.name
                  and media_type_from_filename(path.name) == MediaType.VIDEO)


def named_folder(video: Path, videos: Path) -> str:
    return " ".join(video.parent.relative_to(videos).parts[:FOLDER_PARTS_IN_A_NAME])


def title_of(video: Path, places: NonAiPlaces) -> str:
    return video_title(filed_record(video, places.records), video)


def row_bringing_in(video: Path, places: NonAiPlaces) -> dict:
    filed = datetime.fromtimestamp(video.stat().st_mtime, tz=UTC)
    video_id = str(uuid.uuid4())
    generate_animated_thumbnail(video, places.thumb_dir, name=video_id)
    return {
        **recorded_fields(GenerationSource.NON_AI,
                          non_ai_workflow(named_folder(video, places.videos)),
                          {FOLDER_KEY: video.parent.relative_to(places.videos).as_posix(),
                           TITLE_KEY: title_of(video, places)},
                          (made_at(Made(), filed), filed), action=None),
        "workflow_version": NonAiWorkflow.version, "status": GenerationStatus.COMPLETED,
        "workflow_json": "{}", "prompt_id": video_id,
        "output_files": json.dumps([{"filename": video.name, "library_path": str(video)}]),
        "thumbnail_path": str(generate_thumbnail(video, MediaType.VIDEO, places.thumb_dir,
                                                 name=video_id)),
    }
