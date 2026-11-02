from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from origenerator.evolver_upscales import UPSCALE_SUFFIX
from origenerator.file_refs import frame_name
from origenerator.gallery.signatures import READINGS_KEPT, workflow_output_type
from origenerator.generation_state import GenerationStatus
from origenerator.media import MediaType, media_type_from_filename, sibling_of_type
from origenerator.one_look import is_file
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path, generate_animated_thumbnail

logger = logging.getLogger(__name__)

def parse_file_list(raw) -> list[dict]:
    if not raw:
        return []
    try:
        files = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return files if isinstance(files, list) else []


def row_output_files(row: dict) -> list[dict]:
    return parse_file_list(row.get("output_files"))


_FILE_LISTS = ("output_files", "original_files", "enhance_history")


def with_files_renamed(row: dict, renamed: dict[str, str]) -> dict:
    if not renamed:
        return row
    return {**row, **{column: json.dumps([_renamed(entry, renamed)
                                          for entry in parse_file_list(row[column])])
                      for column in _FILE_LISTS if row.get(column)}}


def _renamed(entry, renamed: dict[str, str]):
    if not isinstance(entry, dict) or entry.get("filename") not in renamed:
        return entry
    return {**entry, "filename": renamed[entry["filename"]]}


@lru_cache(maxsize=READINGS_KEPT)
def frame_names_of(output_files: str | None) -> tuple[str, ...]:
    names = (frame_name(f.get("filename")) for f in parse_file_list(output_files))
    return tuple(name for name in names if name)


def produced_output(row: dict) -> bool:
    return _lists_a_file(row.get("output_files"))


@lru_cache(maxsize=READINGS_KEPT)
def _lists_a_file(output_files: str | None) -> bool:
    return bool(parse_file_list(output_files))


def is_in_progress(row: dict) -> bool:
    return row.get("status") in (GenerationStatus.RUNNING, GenerationStatus.PENDING)


def media_type_of_row(row: dict) -> MediaType:
    return _media_type_of(row.get("output_files"), row.get("workflow_name"))


@lru_cache(maxsize=READINGS_KEPT)
def _media_type_of(output_files: str | None, workflow_name: str | None) -> MediaType:
    for f in parse_file_list(output_files):
        inferred = media_type_from_filename(f.get("filename", ""))
        if inferred:
            return inferred
    return workflow_output_type(workflow_name) or MediaType.IMAGE


def output_file_path(file: dict, places: OutputPlaces) -> Path:
    placed = place_of_its_own(file)
    if placed:
        return Path(placed)
    return places.folder(file.get("subfolder") or "") / (file.get("filename") or "")


def place_of_its_own(file: dict) -> str | None:
    return file.get("path") or file.get("library_path")


_COPY_COUNTER = re.compile(r" \(\d+\)$")


def _stem_before_the_library_renamed_it(stem: str) -> str:
    while True:
        earlier = _COPY_COUNTER.sub("", stem).removesuffix(UPSCALE_SUFFIX)
        if earlier == stem:
            return stem
        stem = earlier


def stem_as_made(path) -> str:
    return _stem_before_the_library_renamed_it(Path(frame_name(str(path))).stem)


def generations_by_stem(rows: list[dict]) -> dict[str, str]:
    by_stem: dict[str, str] = {}
    for row in rows:
        for file in row_output_files(row):
            if stem := Path(frame_name(file.get("filename"))).stem:
                by_stem.setdefault(stem, row["prompt_id"])
    return by_stem


def generation_of_file(path, rows: list[dict]) -> str | None:
    return generations_by_stem(rows).get(stem_as_made(path))


def resolve_preview(row: dict, places: OutputPlaces) -> tuple[Path, str] | None:
    for f in row_output_files(row):
        filename = f.get("filename")
        if not filename:
            continue
        full = output_file_path(f, places)
        rendered_as = media_type_from_filename(filename)
        if rendered_as is not None and is_file(full):
            return full, rendered_as
        break

    thumb = row.get("thumbnail_path")
    if thumb and is_file(thumb):
        return Path(thumb), MediaType.IMAGE

    return None


def make_animated_preview(row: dict, places: OutputPlaces, thumb_dir: Path) -> str | None:
    video = video_file_of(row, places)
    if video is None:
        return None
    result = generate_animated_thumbnail(video, thumb_dir, name=row["prompt_id"])
    return str(result) if result is not None else None


def animated_preview_if_made(row: dict, places: OutputPlaces, thumb_dir: Path) -> str | None:
    if video_file_of(row, places) is None:
        return None
    made = animated_thumbnail_path(thumb_dir, row["prompt_id"])
    return str(made) if made.exists() else None


def video_file_of(row: dict, places: OutputPlaces) -> Path | None:
    preview = resolve_preview(row, places)
    return preview[0] if preview is not None and preview[1] == MediaType.VIDEO else None


def output_disk_files(row: dict, places: OutputPlaces,
                      names: set[str] | None = None) -> list[Path]:
    paths: list[Path] = []
    for f in row_output_files(row):
        filename = f.get("filename")
        if not filename or f.get("library_path") or (names is not None and filename not in names):
            continue
        full = output_file_path(f, places)
        if not full.exists():
            continue
        paths.append(full)
        other = (MediaType.VIDEO if media_type_from_filename(filename) == MediaType.IMAGE
                 else MediaType.IMAGE)
        sidecar = sibling_of_type(full, other)
        if sidecar is not None:
            paths.append(sidecar)
    return paths


def output_file_reference(files: list[dict]) -> str | None:
    for f in files:
        filename = f.get("filename")
        if not filename:
            continue
        if f.get("path"):
            return f["path"]
        subfolder = f.get("subfolder") or ""
        path = f"{subfolder}/{filename}" if subfolder else filename
        return f"{path} [{f.get('type') or 'output'}]"
    return None


def input_image_reference(row: dict | None) -> str | None:
    if not row or media_type_of_row(row) != MediaType.IMAGE:
        return None
    return output_file_reference(row_output_files(row))
