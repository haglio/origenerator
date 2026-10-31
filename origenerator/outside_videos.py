"""The AI videos other sources made, brought in from Evolver's outbox."""
from __future__ import annotations

import itertools
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app_support import favorites, haglio_settings
from app_support.mirrored_tree import library_roots_beside, mirrored_path
from funestra.video_families import seed_group_key
from PIL import Image

from origenerator import config, evolver_agreement
from origenerator.db_generations import library_paths_in
from origenerator.evolver_export import PARTIAL_MARKER
from origenerator.evolver_upscales import filed_upscales
from origenerator.gallery.output import generations_by_stem, parse_file_list, stem_as_made
from origenerator.gallery.signatures import parse_params
from origenerator.gallery.source_image import videos_from_source_image
from origenerator.gallery.tree import settings_folder_key, start_frame_index
from origenerator.generation_state import GenerationSource, GenerationStatus, made_here, source_of
from origenerator.media import MediaType, media_type_from_filename
from origenerator.thumbnail import first_frame_of, generate_thumbnail
from origenerator.workflows.outside import (
    PLACES,
    VideoKind,
    outside_source,
    outside_workflow,
)

FRAME_PIXELS = 2_000_000
VIDEOS_PER_WRITE = 100
JOURNAL_NAME = "origenerator.jsonl"


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
    act: str | None = None
    image_key: tuple[str, str] | None = None
    favorite: bool = False


def record_of(video: Path, records_folder: Path, *, act: str | None = None) -> Record:
    recorded = _recorded(video, records_folder)
    shown, made_from = _block(recorded, "video"), recorded.get("source_image")
    if act is not None:
        shown = {**shown, "action": act}
    image = made_from if isinstance(made_from, dict) else None
    read = {"video": shown, "source_image": image}
    return Record(video=_made(shown, PLACES[MediaType.VIDEO]),
                  image=_made(image, PLACES[MediaType.IMAGE]) if image is not None else None,
                  act=shown.get("action") or None,
                  image_key=seed_group_key(read) if image else None,
                  favorite=recorded.get("favorite") is True)


def mark_a_favorite(video: Path, records_folder: Path) -> bool:
    path = _record_path(video, records_folder)
    if path is None:
        return False
    favorites.mark(path, True)
    return record_of(video, records_folder).favorite


def _recorded(video: Path, records_folder: Path) -> dict:
    path = _record_path(video, records_folder)
    try:
        record = json.loads(path.read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _made(block: dict, places: dict[str, str]) -> Made:
    return Made({place: str(block[key]) for key, place in places.items()
                 if block.get(key) not in (None, "")},
                created=block.get("created") or None)


def _record_path(video: Path, records_folder: Path) -> Path | None:
    return mirrored_path(video, roots=library_roots_beside(records_folder),
                         mirror_root=records_folder, suffix=".json")


def _block(record: dict, name: str) -> dict:
    block = record.get(name)
    return block if isinstance(block, dict) else {}


@dataclass(frozen=True)
class Places:
    upscaled_dir: Path
    records_folder: Path
    frames_dir: Path
    thumb_dir: Path
    skip_sources: frozenset[str]
    library_root: Path
    journal: Path | None


def places_here() -> Places | None:
    evolver = evolver_agreement.evolver_checkout()
    records = evolver_agreement.records_folder(evolver, config.LIBRARY_ROOT)
    if records is None:
        return None
    journals = _journals_folder()
    return Places(upscaled_dir=config.EVOLVER_UPSCALED_DIR, records_folder=records,
                  frames_dir=config.STARTING_FRAMES_DIR, thumb_dir=config.THUMB_DIR,
                  skip_sources=frozenset(source for source in (config.EVOLVER_SOURCE,
                                                               config.GENAU_SOURCE) if source),
                  library_root=config.LIBRARY_ROOT,
                  journal=journals / JOURNAL_NAME if journals else None)


def _journals_folder() -> Path | None:
    try:
        return Path(haglio_settings.value("warm_gun_journal_dir"))
    except haglio_settings.MissingSetting:
        return None


def tell_fun_time(rows: list[dict], favorite: bool) -> None:
    places = places_here()
    if places is not None:
        journal_favorites(places, rows, favorite)


def journal_favorites(places: Places, rows: list[dict], favorite: bool, *, now=time.time) -> None:
    _journal(places, rows, {"event": "favorite" if favorite else "unfavorite"}, now)


def pick_act(db, places: Places, video_row: dict, act: str, *, now=time.time) -> None:
    _journal(places, [video_row], {"event": "action", "action": act}, now)
    db.set_act(video_row["prompt_id"], act)


def _journal(places: Places, rows: list[dict], said: dict, now) -> None:
    videos = [Path(path) for row in rows if source_of(row) == GenerationSource.OUTSIDE
              for path in library_paths_in(row.get("output_files"))]
    if places.journal is None or not videos:
        return
    places.journal.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"t": round(now() * 1000), **said,
                         "path": video.relative_to(places.library_root).as_posix()})
             for video in videos]
    with places.journal.open("a", encoding="utf-8", newline="\n") as journal:
        journal.write("".join(f"{line}\n" for line in lines))


def scan(db, places: Places, *, grab=first_frame_of, videos_per_write: int = VIDEOS_PER_WRITE,
         keep_going=lambda: True) -> int:
    rows = db.list_generations()
    new = [(video, record_of(video.path, places.records_folder))
           for video in outside_videos(places.upscaled_dir, skip_sources=places.skip_sources,
                                       rows=rows,
                                       held=db.library_paths() | db.trashed_library_paths())]
    kinds = _kinds_by_site(rows, new)
    images = _bring_up_to_records(db, places, rows, keep_going, kinds)
    wanted = itertools.takewhile(lambda _new: keep_going(), new)
    brought = (made for video, record in wanted
               if (made := _brought_in(video, record, places, images, grab, kinds)))
    brought_in = 0
    for batch in itertools.batched(brought, videos_per_write):
        db.insert_rows([row for made in batch for row in made])
        brought_in += len(batch)
    return brought_in


def _brought_in(video: OutsideVideo, record: Record, places: Places, images: dict, grab,
                kinds: dict[str, set[VideoKind]]) -> list[dict]:
    image = _image_of(video.source, record)
    made = rows_bringing_in(video, record, frames_dir=places.frames_dir,
                            thumb_dir=places.thumb_dir, grab=grab, image=images.get(image),
                            kind=_named_kind(record, kinds[video.source]))
    if image is not None and image not in images and len(made) == 2:
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


def _bring_up_to_records(db, places: Places, rows: list[dict], keep_going,
                         kinds: dict[str, set[VideoKind]]) -> dict[tuple, dict]:
    said = _said_here(places.journal)
    told_here, acted_here = _favorited_here(said), _acted_here(said)
    frames = _frames_by_file(rows)
    made_here_from_frames = [row for row in rows if made_here(row) and _input_image(row)]
    images: dict[tuple, dict] = {}
    rewritten: dict[str, dict] = {}
    for video_row in _outside_videos_oldest_first(rows):
        if not keep_going():
            break
        path = Path(min(library_paths_in(video_row.get("output_files"))))
        filed = _filed_at(path)
        if filed is None:
            continue
        place, written = path.relative_to(places.library_root).as_posix(), _written_at(path, places)
        record = record_of(path, places.records_folder,
                           act=_picked_since(acted_here.get(place), written))
        frame_row = frames.get(_input_image(video_row))
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
        _take_the_favorite(db, video_row, record, told_here.get(place, 0), written)
    db.set_recorded_fields(list(rewritten.values()))
    db.forget_item_numbers(_numbered_in_another_folder(db))
    return images


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


def _take_the_favorite(db, video_row: dict, record: Record, told_at: float,
                   written: float | None) -> None:
    if written is None or told_at >= written:
        return
    if bool(video_row.get("starred")) != record.favorite:
        db.set_generation_favorite(video_row["prompt_id"], record.favorite)


def _written_at(video: Path, places: Places) -> float | None:
    written = _record_path(video, places.records_folder)
    if written is None or not written.is_file():
        return None
    return written.stat().st_mtime


def _picked_since(picked: tuple[float, str] | None, written: float | None) -> str | None:
    if picked is None or (written is not None and picked[0] < written):
        return None
    return picked[1]


def _said_here(journal: Path | None) -> list[dict]:
    try:
        lines = journal.read_text(encoding="utf-8").splitlines() if journal else []
    except OSError:
        return []
    said = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (isinstance(event, dict) and isinstance(event.get("path"), str)
                and isinstance(event.get("t"), int | float)):
            said.append(event)
    return said


def _favorited_here(said: list[dict]) -> dict[str, float]:
    told: dict[str, float] = {}
    for event in said:
        if event.get("event") in ("favorite", "unfavorite"):
            told[event["path"]] = max(told.get(event["path"], 0), event["t"] / 1000)
    return told


def _acted_here(said: list[dict]) -> dict[str, tuple[float, str]]:
    picks = sorted((event for event in said if event.get("event") == "action"),
                   key=lambda event: event["t"])
    return {event["path"]: (event["t"] / 1000, str(event.get("action") or "")) for event in picks}


def rows_bringing_in(video: OutsideVideo, record: Record, *, frames_dir: Path, thumb_dir: Path,
                     grab=first_frame_of, image: dict | None = None,
                     kind: VideoKind | None = None) -> list[dict]:
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
        _made_at(image or record.video, filed), filed, act=None)


def _video_fields(record: Record, filed: datetime, frame_file: str | None, site: str,
                  kind: VideoKind | None) -> dict:
    return _recorded_fields(
        GenerationSource.OUTSIDE, outside_workflow(site, MediaType.VIDEO, kind),
        {**record.video.params, "input_image": frame_file},
        _made_at(record.video, filed), filed, act=record.act)


def _recorded_fields(source: str, workflow_name: str, params: dict, made: datetime,
                     filed: datetime, *, act: str | None) -> dict:
    return {
        "source": source,
        "workflow_name": workflow_name,
        "params_json": json.dumps(params),
        "positive_prompt": params.get("positive_prompt"),
        "negative_prompt": params.get("negative_prompt"),
        "seed": _seed_number(params.get("seed")),
        "act": act,
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


def _seed_number(seed: str | None) -> int | None:
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
