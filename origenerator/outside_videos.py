from __future__ import annotations

import itertools
import json
import math
import os
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from app_support import kino_folder
from app_support.gallery_rows import VideoRows
from app_support.win32 import mutex_name
from funestra.video_families import seed_group_and_seed
from PIL import Image

from origenerator import config
from origenerator.db_generations import library_paths_in
from origenerator.evolver_export import PARTIAL_MARKER
from origenerator.evolver_upscales import filed_under, filed_upscales
from origenerator.gallery.output import generations_by_stem, parse_file_list, stem_as_made
from origenerator.gallery.signatures import parse_params
from origenerator.gallery.source_image import videos_from_source_image
from origenerator.gallery.tree import settings_folder_key, start_frame_index
from origenerator.generation_state import GenerationSource, GenerationStatus, made_here, source_of
from origenerator.media import MediaType, media_type_from_filename
from origenerator.one_at_a_time import WAIT_S, Turn
from origenerator.thumbnail import (
    first_frame_of,
    generate_animated_thumbnail,
    generate_thumbnail,
)
from origenerator.workflows.outside import (
    PLACES,
    VideoKind,
    outside_source,
    outside_workflow,
    recorded_block,
)

FRAME_PIXELS = 2_000_000
VIDEOS_PER_WRITE = 100


@dataclass(frozen=True)
class OutsideVideo:
    path: Path
    source: str


@dataclass(frozen=True)
class Made:
    params: dict = field(default_factory=dict)
    created: str | None = None


@dataclass(frozen=True)
class Record:
    video: Made = field(default_factory=Made)
    image: Made | None = None
    action: str | None = None
    image_key: tuple[str, str] | None = None
    favorite: bool = False


def record_from(recorded: dict) -> Record:
    shown, made_from = _block(recorded, "video"), recorded.get("source_image")
    image = made_from if isinstance(made_from, dict) else None
    read = {"video": shown, "source_image": image}
    return Record(video=made_of(shown, PLACES[MediaType.VIDEO]),
                  image=made_of(image, PLACES[MediaType.IMAGE]) if image is not None else None,
                  action=shown.get("action") or None,
                  image_key=seed_group_and_seed(read) if image else None,
                  favorite=recorded.get("favorite") is True)


def made_of(block: dict, places: dict[str, str]) -> Made:
    return Made({place: str(block[key]) for key, place in places.items()
                 if block.get(key) not in (None, "")},
                created=block.get("created") or None)


def _block(record: dict, name: str) -> dict:
    block = record.get(name)
    return block if isinstance(block, dict) else {}


@dataclass(frozen=True)
class Places:
    kino: Path
    frames_dir: Path
    thumb_dir: Path
    skip_sources: frozenset[str]
    library_root: Path

    @property
    def upscaled_dir(self) -> Path:
        return kino_folder.upscales_in(self.kino)


def places_here() -> Places:
    return Places(kino=config.KINO_DIR,
                  frames_dir=config.STARTING_FRAMES_DIR, thumb_dir=config.THUMB_DIR,
                  skip_sources=frozenset(source for source in (config.EVOLVER_SOURCE,
                                                               config.GENAU_SOURCE) if source),
                  library_root=config.LIBRARY_ROOT)


def turn_at(db, *, wait_s: float = WAIT_S) -> Turn:
    library = os.path.normcase(os.path.realpath(db.path))
    return Turn(mutex_name("Global\\Origenerator.outside_videos", library), wait_s=wait_s)


def scan_in_turn(db, places: Places, *, wait_s: float = WAIT_S) -> int:
    with turn_at(db, wait_s=wait_s).taken() as ours:
        return scan(db, places) if ours else 0


_LOOK_FOR_THEM = object()


def bring_in_one(db, video: Path, *, places=_LOOK_FOR_THEM, grab=first_frame_of) -> bool:
    places = places_here() if places is _LOOK_FOR_THEM else places
    with turn_at(db).taken() as ours:
        return ours and _brought_in_alone(db, video, places, Record(), grab)


def _brought_in_alone(db, video: Path, places: Places | None, record: Record, grab) -> bool:
    source = None if places is None else filed_under(places.upscaled_dir, video)
    return source is not None and scan(
        db, places, grab=grab, only=(OutsideVideo(video, source), record)) > 0


def take_record(db, video: Path, recorded: dict, *, places=_LOOK_FOR_THEM,
                grab=first_frame_of) -> bool:
    places = places_here() if places is _LOOK_FOR_THEM else places
    record = record_from(recorded)
    with turn_at(db).taken() as ours:
        if not ours:
            return False
        prompt_id = VideoRows(db.list_generations())(video)
        if prompt_id is None:
            if not _brought_in_alone(db, video, places, record, grab):
                return False
            prompt_id = VideoRows(db.list_generations())(video)
        else:
            _write_the_record(db, db.get_generation(prompt_id), record)
    db.set_library_record(prompt_id, **library_record(recorded))
    return True


def library_record(recorded: dict) -> dict:
    upscale = _block(_block(recorded, "provenance"), "upscale")
    kept = {"web_url": recorded.get("web_url"), "library_id": recorded.get("id"),
            "upscale_provenance": json.dumps(upscale) if upscale else None}
    return {column: value for column, value in kept.items() if value}


def _write_the_record(db, video_row: dict, record: Record) -> None:
    if source_of(video_row) != GenerationSource.OUTSIDE:
        return
    rows = db.list_generations()
    record = replace(record, action=video_row.get("action") or record.action)
    path = Path(min(library_paths_in(video_row.get("output_files"))))
    filed = _filed_at(path) or datetime.now(UTC)
    site = outside_source(video_row["workflow_name"])
    kinds = _kinds_by_site(rows, [(OutsideVideo(path, site), record)])
    frame_row = _frames_by_file(rows).get(_input_image(video_row))
    frame_file = _kept_file(frame_row) if frame_row is not None else _input_image(video_row)
    updates = [(video_row, _video_fields(record, filed, frame_file, site,
                                         _named_kind(record, kinds.get(site, set()))))]
    if frame_row is not None:
        updates.append((frame_row, _frame_fields(record, filed, site)))
    db.set_recorded_fields([{"prompt_id": row["prompt_id"], **fields} for row, fields in updates
                            if _differs(row, fields)])
    rows = db.list_generations()
    _bring_up_to_records(db, rows, _kinds_by_site(rows))


def scan(db, places: Places, *, grab=first_frame_of,
         videos_per_write: int = VIDEOS_PER_WRITE,
         only: tuple[OutsideVideo, Record] | None = None) -> int:
    rows = db.list_generations()
    new = [only] if only is not None else [(video, Record()) for video in outside_videos(
        places.upscaled_dir, skip_sources=places.skip_sources, rows=rows,
        held=db.library_paths() | db.trashed_library_paths())]

    kinds = _kinds_by_site(rows, new)
    images = _bring_up_to_records(db, rows, kinds)
    brought = (made for video, record in new
               if (made := _brought_in(video, record, places, images, (grab, kinds))))
    brought_in = 0
    for batch in itertools.batched(brought, videos_per_write):
        db.insert_rows([row for made in batch for row in made])
        brought_in += len(batch)
    return brought_in


_THE_IMAGE_AND_THE_VIDEO = 2


def _brought_in(video: OutsideVideo, record: Record, places: Places, images: dict, grab_and_kinds: tuple) -> list[dict]:
    grab, kinds = grab_and_kinds
    image = _image_of(video.source, record)
    made = rows_bringing_in(video, record, FrameFolders(places.frames_dir, places.thumb_dir),
                            grab=grab,
                            lent=Lent(images.get(image), _named_kind(record, kinds[video.source])))
    if image is not None and image not in images and len(made) == _THE_IMAGE_AND_THE_VIDEO:
        images[image] = made[0]
    return made


def _image_of(site: str, record: Record) -> tuple | None:
    return (site, *record.image_key) if record.image_key else None


def _kind(record: Record) -> VideoKind:
    return VideoKind.IMAGE_TO_VIDEO if record.image is not None else VideoKind.TEXT_TO_VIDEO


def _named_kind(record: Record, kinds_at_its_site: set[VideoKind]) -> VideoKind | None:
    if kinds_at_its_site | {_kind(record)} == {VideoKind.TEXT_TO_VIDEO}:
        return None
    return _kind(record)


def _kinds_by_site(rows: list[dict], new=()) -> dict[str, set[VideoKind]]:
    frames = _frames_by_file(rows)
    kinds: dict[str, set[VideoKind]] = {}
    for video_row in _outside_videos_oldest_first(rows):
        frame = frames.get(_input_image(video_row))
        if frame is not None:
            kinds.setdefault(outside_source(video_row["workflow_name"]), set()).add(
                VideoKind.TEXT_TO_VIDEO if frame["source"] == GenerationSource.STARTING_FRAME
                else VideoKind.IMAGE_TO_VIDEO)
    for video, record in new:
        kinds.setdefault(video.source, set()).add(_kind(record))
    return kinds


def _frames_by_file(rows: list[dict]) -> dict[str, dict]:
    return {file["path"]: row for row in rows
            for file in parse_file_list(row.get("output_files")) if file.get("path")}


def _bring_up_to_records(db, rows: list[dict],
                         kinds: dict[str, set[VideoKind]]) -> dict[tuple, dict]:
    frames = _frames_by_file(rows)
    made_here_from_frames = [row for row in rows if made_here(row) and _input_image(row)]
    images: dict[tuple, dict] = {}
    rewritten: dict[str, dict] = {}
    for video_row in _outside_videos_oldest_first(rows):
        path = Path(min(library_paths_in(video_row.get("output_files"))))
        filed = _filed_at(path)
        if filed is None:
            continue
        frame_row = frames.get(_input_image(video_row))
        record = _record_kept(video_row, frame_row)
        site = outside_source(video_row["workflow_name"])
        image = _image_of(site, record)
        kept = images.get(image)
        if kept is not None and (frame_row is None or frame_row["prompt_id"] != kept["prompt_id"]):
            if frame_row is not None:
                _fold(db, frame_row, kept, made_here_from_frames)
            frame_row = kept
        elif image is not None and frame_row is not None:
            images[image] = frame_row
        frame_file = _kept_file(frame_row) if frame_row is not None else _input_image(video_row)
        updates = [(video_row, _video_fields(record, filed, frame_file, site,
                                             _named_kind(record, kinds.get(site, set()))))]
        if frame_row is not None and frame_row is not kept:
            updates.append((frame_row, _frame_fields(record, filed, site)))
        for row, fields in updates:
            if _differs(row, fields):
                rewritten[row["prompt_id"]] = {"prompt_id": row["prompt_id"], **fields}
    db.set_recorded_fields(list(rewritten.values()))
    db.forget_item_numbers(_numbered_in_another_folder(db))
    return images


def _record_kept(video_row: dict, frame_row: dict | None) -> Record:
    shown = {**recorded_block(parse_params(video_row.get("params_json")), MediaType.VIDEO),
             "created": video_row.get("created_at"), "action": video_row.get("action")}
    image = None
    if frame_row is not None and source_of(frame_row) == GenerationSource.OUTSIDE:
        image = {**recorded_block(parse_params(frame_row.get("params_json")), MediaType.IMAGE),
                 "created": frame_row.get("created_at")}
    return record_from({"video": shown, "source_image": image})


def _numbered_in_another_folder(db) -> list[str]:
    rows = db.list_generations()
    numbered, frames = db.list_item_numbers(), start_frame_index(rows)
    return [row["prompt_id"] for row in rows
            if not made_here(row) and row["prompt_id"] in numbered
            and numbered[row["prompt_id"]][0] != settings_folder_key(row, frames)]


def _outside_videos_oldest_first(rows: list[dict]) -> list[dict]:
    return sorted((row for row in rows if source_of(row) == GenerationSource.OUTSIDE
                   and library_paths_in(row.get("output_files"))), key=lambda row: row["id"])


def _filed_at(video: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(video.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def _input_image(video_row: dict) -> str | None:
    return parse_params(video_row.get("params_json")).get("input_image")


def _kept_file(frame_row: dict) -> str:
    return next(file["path"] for file in parse_file_list(frame_row.get("output_files"))
                if file.get("path"))


def _fold(db, copy: dict, kept: dict, made_here_from_frames: list[dict]) -> None:
    if videos_from_source_image(copy, made_here_from_frames):
        return
    if copy.get("starred") and not kept.get("starred"):
        db.set_generation_favorite(kept["prompt_id"], True)
        kept["starred"] = 1
    if copy.get("image_state") and not kept.get("image_state"):
        db.set_image_state(kept["prompt_id"], copy["image_state"])
        kept["image_state"] = copy["image_state"]
    _forget_frame(db, copy)


def _differs(row: dict, fields: dict) -> bool:
    return any(parse_params(row.get(key)) != parse_params(value) if key == "params_json"
               else row.get(key) != value for key, value in fields.items())


class FrameFolders(NamedTuple):
    frames_dir: Path
    thumb_dir: Path


class Lent(NamedTuple):
    image: dict | None = None
    kind: VideoKind | None = None


def rows_bringing_in(video: OutsideVideo, record: Record, folders: FrameFolders, *,
                     grab=first_frame_of, lent: Lent | None = None) -> list[dict]:
    frames_dir, thumb_dir = folders
    image, kind = lent or Lent()
    frame = grab(video.path)
    if frame is None:
        return []
    filed = datetime.fromtimestamp(video.path.stat().st_mtime, tz=UTC)
    video_id = str(uuid.uuid4())
    if image is None:
        frame_id = str(uuid.uuid4())
        frame_path = _saved_frame(frame, frames_dir / f"{frame_id}.jpg")
        frames = [{**_frame_fields(record, filed, video.source), **_as_brought_in(),
                   "prompt_id": frame_id,
                   "output_files": json.dumps([{"filename": frame_path.name,
                                                "path": str(frame_path)}]),
                   "thumbnail_path": str(generate_thumbnail(frame_path, MediaType.IMAGE,
                                                            thumb_dir, name=frame_id))}]
    else:
        frame_path, frames = Path(_kept_file(image)), []
    generate_animated_thumbnail(video.path, thumb_dir, name=video_id)
    return [*frames, {
        **_video_fields(record, filed, str(frame_path), video.source, kind), **_as_brought_in(),
        "prompt_id": video_id,
        "output_files": json.dumps([{"filename": video.path.name,
                                     "library_path": str(video.path)}]),
        "thumbnail_path": str(generate_thumbnail(frame_path, MediaType.IMAGE, thumb_dir,
                                                 name=video_id)),
        "starred": int(record.favorite),
    }]


def _as_brought_in() -> dict:
    return {"workflow_version": "outside", "status": GenerationStatus.COMPLETED,
            "workflow_json": "{}"}


def _frame_fields(record: Record, filed: datetime, site: str) -> dict:
    image = record.image
    return _recorded_fields(
        GenerationSource.OUTSIDE if image else GenerationSource.STARTING_FRAME,
        outside_workflow(site, MediaType.IMAGE),
        (image or record.video).params,
        (_made_at(image or record.video, filed), filed), action=None)


def _video_fields(record: Record, filed: datetime, frame_file: str | None, site: str,
                  kind: VideoKind | None) -> dict:
    return _recorded_fields(
        GenerationSource.OUTSIDE, outside_workflow(site, MediaType.VIDEO, kind),
        {**record.video.params, "input_image": frame_file},
        (_made_at(record.video, filed), filed), action=record.action)


def _recorded_fields(source: str, workflow_name: str, params: dict, when: tuple[datetime, datetime], *,
                     action: str | None) -> dict:
    made, filed = when
    return {
        "source": source,
        "workflow_name": workflow_name,
        "params_json": json.dumps(params),
        "positive_prompt": params.get("positive_prompt"),
        "negative_prompt": params.get("negative_prompt"),
        "seed": seed_number(params.get("seed")),
        "action": action,
        "created_at": made.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": filed.isoformat(),
    }


def _made_at(made: Made, filed: datetime) -> datetime:
    try:
        when = datetime.fromisoformat(made.created or "")
    except ValueError:
        return filed
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def leave_out_for_good(db, row: dict) -> None:
    if source_of(row) != GenerationSource.OUTSIDE:
        return
    frame = db.get_generation(_id_its_frame_was_filed_under(row))
    if (frame is not None and frame["source"] == GenerationSource.STARTING_FRAME
            and not videos_from_source_image(frame, db.list_generations())):
        _forget_frame(db, frame)
    db.insert_rows([{**row, "source": GenerationSource.LEFT_OUT}])


def _forget_frame(db, frame: dict) -> None:
    db.delete_generation(frame["prompt_id"])
    kept = [file.get("path") for file in parse_file_list(frame["output_files"])]
    for path in filter(None, [*kept, frame["thumbnail_path"]]):
        Path(path).unlink(missing_ok=True)


def _id_its_frame_was_filed_under(video: dict) -> str:
    return Path(parse_params(video.get("params_json")).get("input_image") or "").stem


def _saved_frame(frame: Image.Image, dest: Path) -> Path:
    scale = math.sqrt(FRAME_PIXELS / (frame.width * frame.height))
    if scale < 1:
        frame = frame.resize((round(frame.width * scale), round(frame.height * scale)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.convert("RGB").save(dest, "JPEG", quality=90)
    return dest


def seed_number(seed: str | None) -> int | None:
    try:
        return int(seed) if seed else None
    except ValueError:
        return None


def outside_videos(upscaled_dir, *, skip_sources, rows: list[dict],
                   held: set[str]) -> list[OutsideVideo]:
    made_here = generations_by_stem(rows)
    return [OutsideVideo(path, source) for source, path in filed_upscales(upscaled_dir)
            if source not in skip_sources
            and media_type_from_filename(path.name) == MediaType.VIDEO
            and PARTIAL_MARKER not in path.name
            and str(path) not in held
            and stem_as_made(path) not in made_here]
