from __future__ import annotations

import json
from pathlib import Path

from origenerator.gallery.output import output_file_path, parse_file_list
from origenerator.generation_state import GenerationStatus
from origenerator.output_places import OutputPlaces
from origenerator.record_fold import file_key

_NO_FILES_MOVED = {"moves": [], "subdir": None}


def repair_records(db, places: OutputPlaces) -> int:
    if not places.videos.is_dir():
        return 0
    repaired = _list_each_picture_once(db, db.list_generations())
    return repaired + _drop_records_of_no_picture(db, db.list_generations(), places)


def _list_each_picture_once(db, rows) -> int:
    tidied = 0
    for row in rows:
        listed = parse_file_list(row.get("output_files"))
        once = list({file_key(entry): entry for entry in listed}.values())
        if len(once) == len(listed):
            continue
        db.update_generation(row["prompt_id"], output_files=json.dumps(once))
        tidied += 1
    return tidied


def _drop_records_of_no_picture(db, rows, places: OutputPlaces) -> int:
    dropped = 0
    for row in rows:
        if row.get("status") != GenerationStatus.COMPLETED:
            continue
        if row.get("experiment_verdict"):
            continue
        if not _has_no_picture(row, places):
            continue
        _drop_the_record_only(db, row)
        dropped += 1
    return dropped


def _has_no_picture(row: dict, places: OutputPlaces) -> bool:
    listed = parse_file_list(row.get("output_files"))
    paths = [output_file_path(entry, places) for entry in listed]
    if not paths:
        return True
    if any(path.exists() for path in paths):
        return False
    return all(_folder_holds_anything(path.parent) for path in paths)


def _folder_holds_anything(folder: Path) -> bool:
    return folder.is_dir() and any(folder.iterdir())


def _drop_the_record_only(db, row: dict) -> None:
    db.delete_generation(row["prompt_id"])
    db.record_deletion(row["prompt_id"], row, _NO_FILES_MOVED)
