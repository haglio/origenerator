"""What a generation actually produced on disk: parsing its recorded output
files, classifying their media type, resolving them to previewable or
deletable paths, and tracing a copy of one elsewhere back to its generation.

A row's ``output_files`` are the ground truth the gallery shows — the tree holds
only rows that produced one, a row's media type follows its file rather than its
workflow's declared type, and both the preview panel and delete path resolve
through here. Independent of the folder hierarchy; depends only on the workflow's
declared output type for the pending-row fallback.
"""
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
    """Parse a stored file-list JSON (``output_files``/``original_files``) into
    a list, tolerating bad data."""
    if not raw:
        return []
    try:
        files = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return files if isinstance(files, list) else []


def row_output_files(row: dict) -> list[dict]:
    """Parse a row's ``output_files`` JSON into a list, tolerating bad data."""
    return parse_file_list(row.get("output_files"))


_FILE_LISTS = ("output_files", "original_files", "enhance_history")


def with_files_renamed(row: dict, renamed: dict[str, str]) -> dict:
    """``row`` naming each of its files by the new name ``renamed`` gives it."""
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
    """True when a row recorded at least one output file.

    The gallery is a gallery of results: a generation that failed wrote no file,
    so it has nothing to show. Its folder still appears while it is *in flight*
    (see :func:`is_in_progress`), represented by a live tile until its output
    lands; only a terminal file-less row (an error) is left out entirely.
    """
    return _lists_a_file(row.get("output_files"))


@lru_cache(maxsize=READINGS_KEPT)
def _lists_a_file(output_files: str | None) -> bool:
    return bool(parse_file_list(output_files))


def is_in_progress(row: dict) -> bool:
    """True while a row is still running or waiting its turn (queued).

    Such a row has no output file yet, but its settings folder must appear at
    once — a Generate/re-roll into a brand-new folder needs a node to navigate to
    while it runs. The tree includes it on this basis and its live tile stands in
    for the not-yet-existing thumbnail; a terminal row (completed/error) is judged
    solely by whether it :func:`produced_output`.
    """
    return row.get("status") in (GenerationStatus.RUNNING, GenerationStatus.PENDING)


def media_type_of_row(row: dict) -> MediaType:
    """Classify a row as an image or a video.

    The actual output file is authoritative — a still saved under a video
    workflow's prefix is an image and must not surface among the videos.
    Rows with no file yet (pending) fall back to the workflow's declared type,
    then to an image.
    """
    return _media_type_of(row.get("output_files"), row.get("workflow_name"))


@lru_cache(maxsize=READINGS_KEPT)
def _media_type_of(output_files: str | None, workflow_name: str | None) -> MediaType:
    for f in parse_file_list(output_files):
        inferred = media_type_from_filename(f.get("filename", ""))
        if inferred:
            return inferred
    return workflow_output_type(workflow_name) or MediaType.IMAGE


def output_file_path(file: dict, places: OutputPlaces) -> Path:
    """Where one recorded output file actually sits on disk.

    Normally in the place its subfolder names, under the name it was filed
    under. A file with a place of its own carries it whole: a ``path`` where the
    Trash re-pointed it into its folder, or where a starting frame is kept,
    and a ``library_path`` for another source's video, which this app shows and
    never moves -- so every surface that shows a generation finds its file
    without knowing which of those it is (see :func:`origenerator.trash_collection.trash_items`).
    """
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
    """Locate the file to preview for ``row`` and how to render it.

    Prefers the full-resolution output itself (so videos play and
    images show at full quality), classifying it by extension. Falls back to the
    stored thumbnail — always a still image — when the output is missing. Returns
    ``None`` when nothing displayable can be found.
    """
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
    """A cached looping-WebP preview of a video ``row``, made if it is not yet.

    ``None`` for a non-video row, or when the video file is missing or unreadable
    — the caller then falls back to the row's static thumbnail. The WebP is cached
    on disk (keyed by the row's ``prompt_id``), so only the first request pays the
    frame-sampling cost, which is seconds per video and never the window's to pay.
    """
    video = video_file_of(row, places)
    if video is None:
        return None
    try:
        result = generate_animated_thumbnail(video, thumb_dir, name=row["prompt_id"])
    except Exception as e:
        logger.warning("Animated preview failed for %s: %s", row.get("prompt_id"), e)
        return None
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
    """Every on-disk output file a row owns, for deletion.

    The referenced output file plus any same-stem sidecar of the other media
    type — a video's VHS_VideoCombine metadata PNG, say. Removing the sidecar
    too is what stops a later import from resurrecting the orphan as its own
    entry. Files already absent are skipped.

    ``names`` narrows it to the given filenames (and their sidecars), for a
    delete that takes some of a row's files rather than the row: binning one
    enhancement level leaves the generation and its other versions alone.
    """
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
    """A ``LoadImage`` reference to a generation's first output file -- its
    subfolder and name under an ``[output]`` tag -- or ``None`` when no file has
    a name to reference."""
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
