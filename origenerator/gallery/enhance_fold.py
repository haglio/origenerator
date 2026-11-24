from __future__ import annotations

import json
import logging
from pathlib import Path

from origenerator import fixes_kept
from origenerator.file_refs import reference_path
from origenerator.fix_switches import KEPT_KEY, switch_of
from origenerator.gallery.enhance import (
    enhance_target_id,
    enhance_version_params,
    is_enhance_product_row,
)
from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW, version_settings
from origenerator.gallery.output import (
    media_type_of_row,
    output_file_path,
    parse_file_list,
    row_output_files,
)
from origenerator.gallery.signatures import parse_params
from origenerator.generation_state import GenerationStatus
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.record_fold import file_key

logger = logging.getLogger(__name__)

IN_PLACE_OF = "enhance_in_place_of"


def _history_entries(files: list[dict], params: dict, enhance_row: dict) -> list[dict]:
    settings = version_settings(params)
    return [
        {"filename": f.get("filename"), "params": settings,
         "run_id": enhance_row.get("id"),
         "finished_at": enhance_row.get("completed_at"),
         **_seed_kept(enhance_row)}
        for f in files if f.get("filename")
    ]


def _seed_kept(enhance_row: dict) -> dict:
    seed = parse_params(enhance_row.get("params_json")).get("seed")
    return {"seed": seed} if isinstance(seed, int) else {}


def in_place_of(enhance_row: dict) -> str | None:
    return parse_params(enhance_row.get("params_json")).get(IN_PLACE_OF)


def fold_enhancement(db, enhance_row: dict,
                     image_rows: list[dict] | None = None) -> str | None:
    enhanced_files = row_output_files(enhance_row)
    if not enhanced_files:
        return None
    if image_rows is None:
        image_rows = db.list_generations()
    source_id = enhance_target_id(
        enhance_row, [r for r in image_rows if media_type_of_row(r) == MediaType.IMAGE])
    if source_id is None:
        return None
    source = db.get_generation(source_id)
    source_files = row_output_files(source)
    listed = {file_key(entry) for entry in source_files}
    new_files = [entry for entry in enhanced_files if file_key(entry) not in listed]
    history = parse_file_list(source.get("enhance_history"))
    replaced = in_place_of(enhance_row)
    updates = {
        "output_files": json.dumps(_put_in_at(
            source_files, new_files,
            lambda entry: replaced is not None and entry.get("filename") == replaced)),
        "enhance_history": json.dumps(_put_in_at(
            history, _history_entries(new_files, enhance_version_params(enhance_row), enhance_row),
            lambda entry: (replaced is not None and isinstance(entry, dict)
                           and entry.get("filename") == replaced))),
    }
    if not source.get("original_files"):
        updates["original_files"] = source.get("output_files")
    if enhance_row.get("thumbnail_path"):
        updates["thumbnail_path"] = enhance_row["thumbnail_path"]
    db.update_generation(source_id, **updates)
    db.delete_generation(enhance_row["prompt_id"])
    return source_id


def _put_in_at(listed: list, new: list, is_the_one_replaced) -> list:
    at = next((at for at, entry in enumerate(listed) if is_the_one_replaced(entry)), 0)
    return listed[:at] + new + listed[at:]


def fold_completed_enhancements(db) -> int:
    rows = sorted(db.list_generations(), key=lambda r: r.get("id") or 0)
    pool = [r for r in rows if media_type_of_row(r) == MediaType.IMAGE]
    folded = 0
    for row in rows:
        if row.get("status") != GenerationStatus.COMPLETED:
            continue
        if ((row.get("workflow_name") or "") != ENHANCE_WORKFLOW
                and not is_enhance_product_row(row)):
            continue
        source_id = fold_enhancement(db, row, image_rows=pool)
        if source_id is None:
            continue
        folded += 1
        upgraded = db.get_generation(source_id)
        pool = [r for r in pool if r.get("prompt_id") != row.get("prompt_id")]
        for candidate in pool:
            if candidate.get("prompt_id") == source_id and upgraded is not None:
                candidate.update(upgraded)
    if folded:
        logger.info("Folded %d enhancements into their source images", folded)
    return folded


def enhancements_of_images_gone(rows, *, places: OutputPlaces, input_dir: Path) -> list[dict]:
    return [
        row for row in rows
        if row.get("workflow_name") == ENHANCE_WORKFLOW
        and row.get("status") == GenerationStatus.COMPLETED
        and (image := parse_params(row.get("params_json")).get("input_image"))
        and reference_path(image, places=places, input_dir=input_dir) is None
    ]


def disown_foreign_runs(db) -> int:
    ceiling = db.highest_id_issued()
    if not ceiling:
        return 0
    repaired = 0
    for row in db.list_generations():
        versions = parse_file_list(row.get("enhance_history"))
        owned = [
            {**version, "run_id": None}
            if isinstance(version, dict) and isinstance(version.get("run_id"), int)
            and version["run_id"] > ceiling
            else version
            for version in versions
        ]
        if owned != versions:
            db.update_generation(row["prompt_id"], enhance_history=json.dumps(owned))
            repaired += 1
    if repaired:
        logger.info("Disowned a foreign run id on %d enhanced images", repaired)
    return repaired


_LONG_ENOUGH_TO_HAVE_LANDED = 24 * 60 * 60


def forget_fixes_of_enhancements_gone(db, kept_root: Path, *, now: float) -> int:
    rows = [*db.list_generations(), *(trashed["row"] for trashed in db.list_trashed())]
    listed = {entry.get(KEPT_KEY) for row in rows for entry in row_output_files(row)}
    return fixes_kept.forget_all_but(kept_root, listed,
                                     settled_before=now - _LONG_ENOUGH_TO_HAVE_LANDED)


def finish_fix_switches_cut_short(db, kept_root: Path, places: OutputPlaces) -> int:
    finished = 0
    for row in db.list_generations():
        for entry in row_output_files(row):
            if not isinstance(entry.get(KEPT_KEY), str):
                continue
            image = output_file_path(entry, places)
            for waiting, part, on in fixes_kept.set_down_and_never_put_in_place(
                    kept_root / entry[KEPT_KEY], image):
                switch = switch_of(entry, part)
                if switch is not None and switch.on == on and image.is_file():
                    fixes_kept.put_in_place(waiting, image)
                    finished += 1
                else:
                    waiting.unlink()
    return finished
