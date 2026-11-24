from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app_support import favorites, video_ids
from app_support.mirrored_tree import filed_record, record_path
from app_support.video_names import (
    UPSCALE_SUFFIX,
    full_video_id_of,
    title_while_playing,
    version_group_of,
)

from origenerator import config
from origenerator.evolver_export import could_be_a_finished_video
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.media import MediaType, media_type_from_filename
from origenerator.one_at_a_time import WAIT_S
from origenerator.output_files import library_paths_in
from origenerator.outside_videos import (
    VIDEOS_PER_WRITE,
    Made,
    made_at,
    recorded_fields,
    turn_at,
)
from origenerator.published_actions import publish
from origenerator.record_fold import fold_record_into
from origenerator.thumbnail import generate_animated_thumbnail, generate_thumbnail
from origenerator.workflows.non_ai import (
    FOLDER_KEY,
    TITLE_KEY,
    VERSION_GROUP_KEY,
    VIDEO_ID_KEY,
    NonAiWorkflow,
    folder_named,
    non_ai_workflow,
    where_genaus_flicks_are_named_from,
)


@dataclass(frozen=True)
class Kept:
    folder: Path
    named_from: Path


@dataclass(frozen=True)
class NonAiPlaces:
    videos: Path
    thumb_dir: Path
    records: Path
    more: tuple[Kept, ...] = ()

    @property
    def kept(self) -> tuple[Kept, ...]:
        return (Kept(self.videos, named_from=self.videos), *self.more)

    @property
    def libraries_elsewhere(self) -> tuple[Path, ...]:
        return tuple(kept.named_from for kept in self.more)

    def record_of(self, video: Path) -> dict:
        return filed_record(video, self.records, more_roots=self.libraries_elsewhere)


def places_here() -> NonAiPlaces:
    return NonAiPlaces(videos=config.NON_AI_DIR, thumb_dir=config.THUMB_DIR,
                       records=config.VIDEO_RECORDS_DIR, more=more_places_here())


def more_places_here() -> tuple[Kept, ...]:
    vr = [] if config.VR_DIR is None else [Kept(config.VR_DIR, named_from=config.VR_DIR.parent.parent)]
    return (*vr, *(Kept(folder, named_from=where_genaus_flicks_are_named_from())
                   for folder in config.GENAU_FLICKS_NO_MODEL_MADE))


def scan_in_turn(db, places: NonAiPlaces, *, wait_s: float = WAIT_S) -> int:
    with turn_at(db, wait_s=wait_s).taken() as ours:
        return scan(db, places) if ours else 0


def scan(db, places: NonAiPlaces, *, videos_per_write: int = VIDEOS_PER_WRITE) -> int:
    follow_enhanced_copies(db)
    held = db.library_paths() | db.trashed_library_paths()
    new = ((video, kept) for kept in places.kept for video in non_ai_videos(kept.folder)
           if str(video) not in held)
    brought_in = 0
    for batch in itertools.batched((row_bringing_in(video, kept, places.thumb_dir)
                                    for video, kept in new),
                                   videos_per_write):
        db.insert_rows(list(batch))
        brought_in += len(batch)
    _take_up_the_records(db, places)
    folded = _fold_moved_videos_into_their_items(db)
    if folded:
        _take_up_the_records(db, places)
    return brought_in - folded


def take_up_what_the_records_say(db, places: NonAiPlaces) -> int:
    return follow_enhanced_copies(db) + _take_up_the_records(db, places)


def follow_enhanced_copies(db) -> int:
    followed = 0
    for row in db.list_generations():
        if row["source"] != GenerationSource.NON_AI:
            continue
        files = json.loads(row["output_files"] or "[]")
        now = [_the_copy_that_is_there(entry) for entry in files]
        if now != files:
            db.update_generation(row["prompt_id"], output_files=json.dumps(now))
            followed += 1
    return followed


def _fold_moved_videos_into_their_items(db) -> int:
    rows = db.list_generations()
    gone, there = {}, {}
    for row in rows:
        given = (json.loads(row["params_json"]).get(VIDEO_ID_KEY)
                 if row["source"] == GenerationSource.NON_AI else None)
        if given:
            files = library_paths_in(row["output_files"])
            (there if any(Path(video).exists() for video in files) else gone)[given] = row
    moved = [(gone[given], row) for given, row in there.items() if given in gone]
    for keeper, folded in moved:
        _take_the_place_of(db, keeper, folded)
        fold_record_into(db, rows, folded, keeper)
        db.delete_generation(folded["prompt_id"])
    if moved:
        publish(db)
    return len(moved)


def _take_the_place_of(db, keeper: dict, folded: dict) -> None:
    db.update_generation(keeper["prompt_id"], output_files=folded["output_files"])
    db.set_workflow_name(keeper["prompt_id"], folded["workflow_name"])
    db.set_params_json(keeper["prompt_id"], json.dumps(
        {**json.loads(keeper["params_json"]),
         FOLDER_KEY: json.loads(folded["params_json"])[FOLDER_KEY]}))


def _the_copy_that_is_there(entry: dict) -> dict:
    video = Path(entry["library_path"])
    enhanced = video.with_name(f"{video.stem}{UPSCALE_SUFFIX}{video.suffix}")
    if video.exists() or not enhanced.is_file():
        return entry
    return {**entry, "filename": enhanced.name, "library_path": str(enhanced)}


def _take_up_the_records(db, places: NonAiPlaces) -> int:
    recorded = [(row, Path(video), places.record_of(Path(video)))
                for row in db.list_generations() if row["source"] == GenerationSource.NON_AI
                for video in library_paths_in(row["output_files"])]
    item_of = {given: row["prompt_id"] for row, _video, record in recorded
               if (given := video_ids.recorded_id(record)) is not None}
    return sum(_take_up(db, row, video, record, item_of) for row, video, record in recorded)


def _take_up(db, row: dict, video: Path, record: dict, item_of: dict[str, str]) -> bool:
    cut_from = item_of.get(full_video_id_of(record))
    relinked = row.get("trimmed_from") != cut_from
    if relinked:
        db.set_cut_from(row["prompt_id"], cut_from)
    return _take_up_its_name_and_star(db, row, video, record) or relinked


def _take_up_its_name_and_star(db, row: dict, video: Path, record: dict) -> bool:
    params = json.loads(row["params_json"])
    given = video_ids.recorded_id(record)
    recorded = {**params, TITLE_KEY: title_while_playing(record, video),
                VERSION_GROUP_KEY: version_group_of(record),
                **({VIDEO_ID_KEY: given} if given is not None else {})}
    renamed = recorded != params
    if renamed:
        db.set_params_json(row["prompt_id"], json.dumps(recorded))
    favorite = favorites.is_favorite(record)
    restarred = bool(row["starred"]) != favorite
    if restarred:
        db.set_generation_favorite(row["prompt_id"], favorite)
    return renamed or restarred


def tell_fun_time_of_favorites(rows, favorite: bool, records: Path, *,
                               libraries_elsewhere: tuple[Path, ...] = ()) -> None:
    for row in rows:
        if row["source"] == GenerationSource.NON_AI:
            for video in library_paths_in(row["output_files"]):
                favorites.mark(record_path(Path(video), records, more_roots=libraries_elsewhere),
                               favorite)


def non_ai_videos(folder: Path) -> list[Path]:
    return sorted(path for path in (folder.rglob("*") if folder.is_dir() else ())
                  if path.is_file() and could_be_a_finished_video(path.name)
                  and media_type_from_filename(path.name) == MediaType.VIDEO)


def named_folder(video: Path, named_from: Path) -> str:
    return folder_named(video.parent, named_from)


def row_bringing_in(video: Path, kept: Kept, thumb_dir: Path) -> dict:
    filed = datetime.fromtimestamp(video.stat().st_mtime, tz=UTC)
    prompt_id = str(uuid.uuid4())
    generate_animated_thumbnail(video, thumb_dir, name=prompt_id)
    return {
        **recorded_fields(GenerationSource.NON_AI,
                          non_ai_workflow(named_folder(video, kept.named_from)),
                          {FOLDER_KEY: video.parent.relative_to(kept.named_from).as_posix()},
                          (made_at(Made(), filed), filed), action=None),
        "workflow_version": NonAiWorkflow.version, "status": GenerationStatus.COMPLETED,
        "workflow_json": "{}", "prompt_id": prompt_id,
        "output_files": json.dumps([{"filename": video.name, "library_path": str(video)}]),
        "thumbnail_path": str(generate_thumbnail(video, MediaType.VIDEO, thumb_dir,
                                                 name=prompt_id)),
    }
