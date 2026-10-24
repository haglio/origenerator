from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from origenerator.gallery.output import parse_file_list
from origenerator.generation_state import GenerationStatus
from origenerator.importer import graph_in_file, recipe_of
from origenerator.output_places import OutputPlaces
from origenerator.record_fold import file_key, fold_record_into

_NO_FILES_MOVED = {"moves": [], "subdir": None}


def repair_records(db, places: OutputPlaces) -> int:
    if not places.videos.is_dir():
        return 0
    repaired = _list_each_picture_once(db, db.list_generations())
    repaired += _leave_one_record_per_picture(db, db.list_generations(), places)
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


def _leave_one_record_per_picture(db, rows, places: OutputPlaces) -> int:
    folded = 0
    for (subfolder, filename), claimants in _claimants_by_picture(rows).items():
        if len(claimants) < 2:
            continue
        keeper = _the_one_that_made_it(claimants, places.folder(subfolder) / filename)
        for row in claimants:
            if row["prompt_id"] == keeper["prompt_id"]:
                continue
            _stop_claiming(db, row, (subfolder, filename))
            if parse_file_list(row.get("output_files")):
                folded += 1
                continue
            fold_record_into(db, rows, row, keeper)
            _drop_the_record_only(db, row)
            folded += 1
    return folded


def _stop_claiming(db, row: dict, picture: tuple[str, str]) -> None:
    left = [entry for entry in parse_file_list(row.get("output_files"))
            if file_key(entry) != picture]
    row["output_files"] = json.dumps(left)
    db.update_generation(row["prompt_id"], output_files=row["output_files"])


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
    paths = [places.folder(subfolder) / filename
             for subfolder, filename in map(file_key, listed)]
    if not paths:
        return True
    if any(path.exists() for path in paths):
        return False
    return all(_folder_holds_anything(path.parent) for path in paths)


def _folder_holds_anything(folder: Path) -> bool:
    return folder.is_dir() and any(folder.iterdir())


def _claimants_by_picture(rows) -> dict[tuple[str, str], list[dict]]:
    claimants: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for row in rows:
        for entry in parse_file_list(row.get("output_files")):
            key = file_key(entry)
            if key[1]:
                claimants[key][row["prompt_id"]] = row
    return {key: list(by_id.values()) for key, by_id in claimants.items()}


def _the_one_that_made_it(claimants: list[dict], path: Path) -> dict:
    in_file = graph_in_file(path, path.suffix.lower()) if path.exists() else {}
    wrote_it = [row for row in claimants
                if in_file and recipe_of(row) == in_file]
    return min(wrote_it or claimants, key=lambda row: row["id"])


def _drop_the_record_only(db, row: dict) -> None:
    db.delete_generation(row["prompt_id"])
    db.record_deletion(row["prompt_id"], row, _NO_FILES_MOVED)
