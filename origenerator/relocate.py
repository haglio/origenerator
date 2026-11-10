from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from origenerator.funscript import funscript_path_for
from origenerator.gallery.output import parse_file_list, place_of_its_own
from origenerator.output_places import OutputPlaces

logger = logging.getLogger(__name__)

FILE_LISTS = ("output_files", "original_files")


# ComfyUI numbers saved files per filename prefix, so two subfolders can hold one name.
def _by_name(places: OutputPlaces) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for path, subfolder in places.files():
        index[path.name].add(subfolder)
    return index


def _followed(files: list, index: dict[str, set[str]], places: OutputPlaces) -> int:
    moved = 0
    for record in files:
        if not isinstance(record, dict) or place_of_its_own(record):
            continue
        name = record.get("filename") or ""
        holders = index.get(name, set())
        was = record.get("subfolder") or ""
        if len(holders) != 1 or was in holders:
            continue
        record["subfolder"] = next(iter(holders))
        _move_script(places.folder(was) / name, places.folder(record["subfolder"]) / name,
                     places)
        moved += 1
    return moved


def _move_script(was: Path, now: Path, places: OutputPlaces) -> None:
    script = funscript_path_for(was, places=places)
    destination = funscript_path_for(now, places=places)
    if script.is_file() and not destination.exists():
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            script.rename(destination)
        except OSError as e:
            logger.warning("A moved video's script stayed at %s: %s", script, e)


def relocate_moved_outputs(db, places: OutputPlaces) -> int:
    index = _by_name(places)
    moved = 0
    for row in db.list_generations():
        updates = {}
        for column in FILE_LISTS:
            files = parse_file_list(row.get(column))
            followed = _followed(files, index, places) if files else 0
            if followed:
                updates[column] = json.dumps(files)
                moved += followed
        if updates:
            db.update_generation(row["prompt_id"], **updates)
    return moved
