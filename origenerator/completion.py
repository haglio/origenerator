"""Turn a finished ComfyUI job's history into what a DB row records.

Every path that completes a generation — the Generate tab, a gallery re-roll,
and the startup reconciler — needs the same three things out of ComfyUI's
history: the output files, a thumbnail for them, and how long the run took.
Defining that once here keeps those paths from drifting apart, and keeps it
Qt-free so the reconciler can use it without a running UI.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from origenerator.config import COMFYUI_INPUT_DIR, COMFYUI_TEMP_DIR, MOTION_DEFAULT_HZ
from origenerator.file_refs import reference_path
from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    synthesize_funscript,
    write_funscript,
)
from origenerator.media import MediaType
from origenerator.thumbnail import generate_thumbnail
from origenerator.timing import execution_duration_seconds

logger = logging.getLogger(__name__)


def extract_completion(workflow, history_data, output_dir: Path, thumb_dir: Path, name,
                       params: dict | None = None):
    """Return ``(output_files, thumbnail_path | None, duration | None)`` for a run.

    ``output_files`` is drawn from ``history_data`` via the workflow's own output
    node; the thumbnail is rendered from the first file that exists on disk (named
    by ``name`` so it's uniquely owned); ``duration`` is parsed from the history's
    execution timestamps. The thumbnail and duration are best-effort — a failure
    in either yields ``None`` rather than stranding an otherwise-finished run.
    ``params`` is the run's parameter dict; a track-authored workflow derives its
    exact funscript from it (without it the metronome fallback stands in).
    """
    files = workflow.extract_output_info(history_data)
    thumb = _make_thumbnail(workflow, files, output_dir, thumb_dir, name)
    _write_video_funscript(workflow, files, output_dir, params)
    try:
        duration = execution_duration_seconds(history_data)
    except Exception as e:
        logger.warning("Duration parse failed for %s: %s", name, e)
        duration = None
    return files, thumb, duration


def _first_output_file(files, output_dir: Path) -> Path | None:
    """The on-disk path of a run's first output, if it exists — the file both the
    thumbnail and the funscript are made from."""
    if not files:
        return None
    first = files[0]
    source = output_dir / first.get("subfolder", "") / first["filename"]
    return source if source.exists() else None


def _write_video_funscript(workflow, files, output_dir: Path, params: dict | None):
    """ComfyUI gives a deleted video's filename to the next video it saves, and
    the deleted one's script is still where the new one's goes, so the finished
    video's own script is written over it."""
    if workflow.output_type != MediaType.VIDEO:
        return
    source = _first_output_file(files, output_dir)
    if source is None:
        return
    try:
        authored = workflow.authored_actions(params) if params else None
        kept = _script_kept_from(workflow, params, output_dir)
        if authored:
            write_funscript(funscript_path_for(source, output_dir=output_dir), authored)
        elif kept is not None:
            destination = funscript_path_for(source, output_dir=output_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(kept, destination)
        else:
            synthesize_funscript(source, hz=MOTION_DEFAULT_HZ, output_dir=output_dir)
    except Exception as e:
        logger.warning("Funscript generation failed for %s: %s", source, e)


def _script_kept_from(workflow, params: dict | None, output_dir: Path) -> Path | None:
    """The script of the video this run's output keeps the timing of (an
    enhancement's source), when that video has one."""
    reference = workflow.script_source(params) if params else None
    if not reference:
        return None
    video = reference_path(reference, output_dir=output_dir, input_dir=COMFYUI_INPUT_DIR,
                           temp_dir=COMFYUI_TEMP_DIR)
    return funscript_of(video, output_dir=output_dir) if video is not None else None


def _make_thumbnail(workflow, files, output_dir: Path, thumb_dir: Path, name):
    source = _first_output_file(files, output_dir)
    if source is None:
        return None
    try:
        thumb_dir.mkdir(parents=True, exist_ok=True)
        return str(generate_thumbnail(source, workflow.output_type, thumb_dir, name=name))
    except Exception as e:
        logger.warning("Thumbnail generation failed for %s: %s", source, e)
        return None
