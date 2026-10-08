from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from origenerator.gallery.output import parse_file_list
from origenerator.generation_state import GenerationStatus
from origenerator.importer import graph_from_text, graph_in_file

_NO_FILES_MOVED = {"moves": [], "subdir": None}


def repair_records(db, output_dir: Path) -> int:
    if not output_dir.is_dir():
        return 0
    repaired = _list_each_picture_once(db, db.list_generations())
    repaired += _leave_one_record_per_picture(db, db.list_generations(), output_dir)
    return repaired + _drop_records_of_no_picture(db, db.list_generations(), output_dir)


def _list_each_picture_once(db, rows) -> int:
    tidied = 0
    for row in rows:
        listed = parse_file_list(row.get("output_files"))
        once = list({_file_key(entry): entry for entry in listed}.values())
        if len(once) == len(listed):
            continue
        db.update_generation(row["prompt_id"], output_files=json.dumps(once))
        tidied += 1
    return tidied


def _leave_one_record_per_picture(db, rows, output_dir: Path) -> int:
    folded = 0
    for (subfolder, filename), claimants in _claimants_by_picture(rows).items():
        if len(claimants) < 2:
            continue
        keeper = _the_one_that_made_it(claimants, output_dir / subfolder / filename)
        for row in claimants:
            if row["prompt_id"] == keeper["prompt_id"]:
                continue
            _stop_claiming(db, row, (subfolder, filename))
            if parse_file_list(row.get("output_files")):
                folded += 1
                continue
            _carry_over_what_the_user_put_on_it(db, row, keeper)
            _repoint_at_the_record_that_stays(db, rows, row, keeper)
            _drop_the_record_only(db, row)
            folded += 1
    return folded


def _stop_claiming(db, row: dict, picture: tuple[str, str]) -> None:
    left = [entry for entry in parse_file_list(row.get("output_files"))
            if _file_key(entry) != picture]
    row["output_files"] = json.dumps(left)
    db.update_generation(row["prompt_id"], output_files=row["output_files"])


def _carry_over_what_the_user_put_on_it(db, folded: dict, keeper: dict) -> None:
    if folded.get("starred") and not keeper.get("starred"):
        db.set_generation_favorite(keeper["prompt_id"], True)
    inherited = {column: folded[column]
                 for column in ("enhance_history", "original_files", "thumbnail_path")
                 if folded.get(column) and not keeper.get(column)}
    if inherited:
        db.update_generation(keeper["prompt_id"], **inherited)


def _repoint_at_the_record_that_stays(db, rows, folded: dict, keeper: dict) -> None:
    gone, stays = folded["prompt_id"], keeper["prompt_id"]
    for row in rows:
        if row.get("enhance_of") == gone:
            db.set_enhance_target(row["prompt_id"], stays)
    for bookmark in db.folder_meta_full():
        if bookmark.get("ref_prompt_id") == gone:
            db.upsert_folder_meta(bookmark["folder_key"],
                                  custom_name=bookmark.get("custom_name"),
                                  favorite=bool(bookmark.get("starred")),
                                  level=bookmark.get("level"), ref_prompt_id=stays)
    for item in db.custom_folder_items_full():
        if item.get("ref_prompt_id") == gone:
            db.stamp_custom_folder_item(item["folder_id"], item["folder_key"],
                                        level=item.get("level"), ref_prompt_id=stays)


def _drop_records_of_no_picture(db, rows, output_dir: Path) -> int:
    dropped = 0
    for row in rows:
        if row.get("status") != GenerationStatus.COMPLETED:
            continue
        if row.get("experiment_verdict"):
            continue
        if not _has_no_picture(row, output_dir):
            continue
        _drop_the_record_only(db, row)
        dropped += 1
    return dropped


def _has_no_picture(row: dict, output_dir: Path) -> bool:
    listed = parse_file_list(row.get("output_files"))
    paths = [output_dir / subfolder / filename
             for subfolder, filename in map(_file_key, listed)]
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
            key = _file_key(entry)
            if key[1]:
                claimants[key][row["prompt_id"]] = row
    return {key: list(by_id.values()) for key, by_id in claimants.items()}


def _file_key(entry: dict) -> tuple[str, str]:
    return entry.get("subfolder") or "", entry.get("filename") or ""


def _the_one_that_made_it(claimants: list[dict], path: Path) -> dict:
    in_file = graph_in_file(path, path.suffix.lower()) if path.exists() else {}
    wrote_it = [row for row in claimants
                if in_file and graph_from_text(row.get("workflow_json") or "") == in_file]
    return min(wrote_it or claimants, key=lambda row: row["id"])


def _drop_the_record_only(db, row: dict) -> None:
    db.delete_generation(row["prompt_id"])
    db.record_deletion(row["prompt_id"], row, _NO_FILES_MOVED)
