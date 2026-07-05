"""Turn a finished ComfyUI job's history into what a DB row records.

Every path that completes a generation — the Generate tab, a gallery re-roll,
and the startup reconciler — needs the same three things out of ComfyUI's
history: the output files, a thumbnail for them, and how long the run took.
Defining that once here keeps those paths from drifting apart, and keeps it
Qt-free so the reconciler can use it without a running UI.
"""

import logging
from pathlib import Path

from origenerator.config import STROKE_DEFAULT_HZ
from origenerator.funscript import ensure_funscript
from origenerator.thumbnail import generate_thumbnail
from origenerator.timing import execution_duration_seconds

logger = logging.getLogger(__name__)


def extract_completion(workflow, history_data, output_dir: Path, thumb_dir: Path, name):
    """Return ``(output_files, thumbnail_path | None, duration | None)`` for a run.

    ``output_files`` is drawn from ``history_data`` via the workflow's own output
    node; the thumbnail is rendered from the first file that exists on disk (named
    by ``name`` so it's uniquely owned); ``duration`` is parsed from the history's
    execution timestamps. The thumbnail and duration are best-effort — a failure
    in either yields ``None`` rather than stranding an otherwise-finished run.
    """
    files = workflow.extract_output_info(history_data)
    thumb = _make_thumbnail(workflow, files, output_dir, thumb_dir, name)
    _ensure_video_funscript(workflow, files, output_dir)
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


def _ensure_video_funscript(workflow, files, output_dir: Path):
    """Synthesize a funscript beside a finished video (best-effort, videos only).

    Runs on the same shared path as thumbnailing, so every completion route — the
    Generate tab, a gallery re-roll, the startup reconciler — leaves a ``.funscript``
    next to each new video. Idempotent (``ensure_funscript`` skips an existing one)
    and swallow-and-log on failure, so it can never strand a real completion.
    """
    if workflow.output_type != "video":
        return
    source = _first_output_file(files, output_dir)
    if source is None:
        return
    try:
        ensure_funscript(source, loop=workflow.looping, hz=STROKE_DEFAULT_HZ)
    except Exception as e:
        logger.warning("Funscript generation failed for %s: %s", source, e)


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
