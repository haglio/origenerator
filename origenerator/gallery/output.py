"""What a generation actually produced on disk: parsing its recorded output
files, classifying their media type, and resolving them to previewable or
deletable paths.

A row's ``output_files`` are the ground truth the gallery shows — the tree holds
only rows that produced one, a row's media type follows its file rather than its
workflow's declared type, and both the preview panel and delete path resolve
through here. Independent of the folder hierarchy; depends only on the workflow's
declared output type for the pending-row fallback.
"""

import json
import logging
from pathlib import Path

from origenerator.media import media_type_from_filename, sibling_of_type
from origenerator.gallery.signatures import workflow_output_type
from origenerator.thumbnail import generate_animated_thumbnail

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


def produced_output(row: dict) -> bool:
    """True when a row recorded at least one output file.

    The gallery is a gallery of results: a generation that failed wrote no file,
    so it has nothing to show. Its folder still appears while it is *in flight*
    (see :func:`is_in_progress`), represented by a live tile until its output
    lands; only a terminal file-less row (an error) is left out entirely.
    """
    return bool(row_output_files(row))


def is_in_progress(row: dict) -> bool:
    """True while a row is still running or waiting its turn (queued).

    Such a row has no output file yet, but its settings folder must appear at
    once — a Generate/re-roll into a brand-new folder needs a node to navigate to
    while it runs. The tree includes it on this basis and its live tile stands in
    for the not-yet-existing thumbnail; a terminal row (completed/error) is judged
    solely by whether it :func:`produced_output`.
    """
    return row.get("status") in ("running", "pending")


def media_type_of_row(row: dict) -> str:
    """Classify a row as ``"image"`` or ``"video"``.

    The actual output file is authoritative — a still saved under a video
    workflow's prefix is an image and must not surface in the Videos folder.
    Rows with no file yet (pending) fall back to the workflow's declared type,
    then to ``"image"``.
    """
    for f in row_output_files(row):
        inferred = media_type_from_filename(f.get("filename", ""))
        if inferred:
            return inferred
    return workflow_output_type(row.get("workflow_name")) or "image"


def output_file_path(file: dict, output_dir: Path) -> Path:
    """Where one recorded output file actually sits on disk.

    Normally under ``output_dir``, at the subfolder and name ComfyUI wrote it
    to. A file the recovery bin has re-pointed carries an absolute ``path`` of
    its own — its place inside the trash — so a deleted item's row resolves to
    the files it still has rather than to where they used to be, and every
    surface that shows a generation follows it there without having to know the
    bin exists (see :func:`origenerator.recovery.bin_items`).
    """
    moved = file.get("path")
    if moved:
        return Path(moved)
    return output_dir / (file.get("subfolder") or "") / (file.get("filename") or "")


def resolve_preview(row: dict, output_dir: Path) -> tuple[Path, str] | None:
    """Locate the file to preview for ``row`` and how to render it.

    Prefers the full-resolution output under ``output_dir`` (so videos play and
    images show at full quality), classifying it by extension. Falls back to the
    stored thumbnail — always a still image — when the output is missing. Returns
    ``None`` when nothing displayable can be found.
    """
    for f in row_output_files(row):
        filename = f.get("filename")
        if not filename:
            continue
        full = output_file_path(f, output_dir)
        rendered_as = media_type_from_filename(filename)
        if rendered_as is not None and full.exists():
            return full, rendered_as
        break

    thumb = row.get("thumbnail_path")
    if thumb and Path(thumb).exists():
        return Path(thumb), "image"

    return None


def animated_preview_path(row: dict, output_dir: Path, thumb_dir: Path) -> str | None:
    """A cached looping-WebP preview of a video ``row``, generated on first need.

    ``None`` for a non-video row, or when the video file is missing or unreadable
    — the caller then falls back to the row's static thumbnail. The WebP is cached
    on disk (keyed by the row's ``prompt_id``), so only the first request pays the
    frame-sampling cost; every gallery surface that shows a video tile resolves
    its moving preview through here.
    """
    preview = resolve_preview(row, output_dir)
    if preview is None or preview[1] != "video":
        return None
    try:
        result = generate_animated_thumbnail(preview[0], thumb_dir, name=row["prompt_id"])
    except Exception as e:
        logger.warning("Animated preview failed for %s: %s", row.get("prompt_id"), e)
        return None
    return str(result) if result is not None else None


def output_disk_files(row: dict, output_dir: Path,
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
        if not filename or (names is not None and filename not in names):
            continue
        full = output_file_path(f, output_dir)
        if not full.exists():
            continue
        paths.append(full)
        other = "video" if media_type_from_filename(filename) == "image" else "image"
        sidecar = sibling_of_type(full, other)
        if sidecar is not None:
            paths.append(sidecar)
    return paths


def output_file_reference(files: list[dict]) -> str | None:
    """A ``LoadImage``-resolvable reference to a generation's first output file.

    A saved file lives in ComfyUI's output dir, so the reference carries its
    subfolder and an ``[output]`` tag (LoadImage validates by file existence via
    that annotation, not by input-folder membership). Feeds a re-rolled i2v its
    freshly generated start frame. ``None`` when no file has a name to reference.
    """
    for f in files:
        filename = f.get("filename")
        if not filename:
            continue
        subfolder = f.get("subfolder") or ""
        path = f"{subfolder}/{filename}" if subfolder else filename
        return f"{path} [{f.get('type') or 'output'}]"
    return None
