from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from origenerator import fixes_kept
from origenerator.config import OUTPUT_PLACES
from origenerator.fix_switches import FIXES_KEY, KEPT_KEY
from origenerator.gallery.output import output_file_path
from origenerator.generation_state import GenerationStatus
from origenerator.item_shape import shape_its_files_say
from origenerator.library_filing import file_into_library
from origenerator.output_places import OutputFolders, OutputPlaces
from origenerator.thumbnail import animate_if_video, generate_thumbnail
from origenerator.timing import execution_duration_seconds
from origenerator.video_lengths import as_recorded, video_length_of
from origenerator.workflows.fix_finding import parts_found_by, saved_before_each_fix

logger = logging.getLogger(__name__)


def extract_completion(workflow, history_data, folders: OutputFolders, prompt_id):
    places, thumb_dir = folders
    made = _with_what_each_fix_redrew(workflow.extract_output_info(history_data), history_data,
                                      places, fixes_kept.folder_beside(thumb_dir), prompt_id)
    files = file_into_library(made, places, prompt_id)
    thumb = _make_thumbnail(workflow, files, places, thumb_dir, prompt_id)
    source = _first_output_file(files, places)
    if source is not None:
        animate_if_video(source, thumb_dir, name=prompt_id)
    try:
        duration = execution_duration_seconds(history_data)
    except Exception as e:
        logger.warning("Duration parse failed for %s: %s", prompt_id, e)
        duration = None
    return files, thumb, duration


def _with_what_each_fix_redrew(made: list[dict], history_data: dict, places: OutputPlaces,
                               kept_root: Path, prompt_id) -> list[dict]:
    befores = [_as_comfyui_saved(record, places) for record in saved_before_each_fix(history_data)]
    try:
        parts = parts_found_by(history_data)
        if not befores or not made or sorted(parts) != list(range(len(befores))):
            return made
        fixes = fixes_kept.keep(
            [*befores, _as_comfyui_saved(made[0], places)],
            [parts[at].name for at in range(len(befores))], kept_root / prompt_id)
    except (OSError, ValueError) as e:
        logger.warning("Keeping what each fix redrew failed for %s: %s", prompt_id, e)
        return made
    finally:
        for before in befores:
            before.unlink(missing_ok=True)
    if not fixes:
        return made
    return [{**made[0], FIXES_KEY: fixes, KEPT_KEY: prompt_id}, *made[1:]]


def _as_comfyui_saved(record: dict, places: OutputPlaces) -> Path:
    return places.comfyui / (record.get("subfolder") or "") / record["filename"]


def _first_output_file(files, places: OutputPlaces) -> Path | None:
    if not files:
        return None
    source = output_file_path(files[0], places)
    return source if source.exists() else None


def _make_thumbnail(workflow, files, places: OutputPlaces, thumb_dir: Path, name):
    source = _first_output_file(files, places)
    if source is None:
        return None
    try:
        thumb_dir.mkdir(parents=True, exist_ok=True)
        return str(generate_thumbnail(source, workflow.output_type, thumb_dir, name=name))
    except Exception as e:
        logger.warning("Thumbnail generation failed for %s: %s", source, e)
        return None


def animate_before_filing(workflow, history_data, places: OutputPlaces, thumb_dir: Path,
                         prompt_id) -> None:
    files = workflow.extract_output_info(history_data)
    if files:
        saved = _as_comfyui_saved(files[0], places)
        animate_if_video(saved, thumb_dir, name=prompt_id)


def mark_generation_completed(db, prompt_id, files, thumb_path, duration):
    fields = {
        "status": GenerationStatus.COMPLETED,
        "output_files": json.dumps(files),
        "thumbnail_path": thumb_path,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if duration is not None:
        fields["duration_seconds"] = duration
    finished = {**(db.get_generation(prompt_id) or {}), **fields}
    fields["shape"] = shape_its_files_say(finished)
    db.update_generation(prompt_id, **fields)
    length = video_length_of(finished, OUTPUT_PLACES)
    if length is not None:
        db.set_library_record(prompt_id, **as_recorded(length))
