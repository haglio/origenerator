from __future__ import annotations

import json
import logging
import uuid
from itertools import islice
from pathlib import Path

from origenerator import gallery, points_of_interest
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_inputs import file_named_by
from origenerator.config import LIBRARY_STATE_DIR
from origenerator.media import MediaType
from origenerator.workflows.detail_parts import detail_fix_passes
from origenerator.workflows.fix_finding import finding_nodes, parts_found_by

logger = logging.getLogger(__name__)

RUNS_PER_ABSENCE = 600
RECORD = LIBRARY_STATE_DIR / "pictures_being_looked_over.json"
_IMAGE = "image"


def queue_finding_for_the_absence(db, client) -> int:
    if is_branch_session() or client is None:
        return 0
    return queue_finding(db.list_generations(), client, RECORD)


def queue_finding(rows: list[dict], client, record: Path, limit: int = RUNS_PER_ABSENCE) -> int:
    waiting = _read(record)
    asked = {(one["row"], one["file"]) for one in waiting.values()}
    to_ask = ((row, version) for row, version in images_to_look_over(rows)
              if (row["prompt_id"], version.file["filename"]) not in asked
              and file_named_by(_reference_to(version), client.folders) is not None)
    batch = {str(uuid.uuid4()): image for image in islice(to_ask, limit)}
    _write(record, waiting | {prompt_id: _noted(*image) for prompt_id, image in batch.items()})
    queued = 0
    for prompt_id, (row, version) in batch.items():
        try:
            client.submit_job(finding_graph(version), prompt_id)
        except Exception as e:
            logger.warning("ComfyUI took no more images to look over: %s", e)
            break
        waiting[prompt_id] = _noted(row, version)
        queued += 1
    _write(record, waiting)
    if queued:
        logger.info("Queued %d image(s) to look over for their places while the app is closed", queued)
    return queued


def _noted(row: dict, version: gallery.EnhanceVersion) -> dict:
    return {"row": row["prompt_id"], "file": version.file["filename"]}


def fold_found_places(db, client, record: Path) -> int:
    folded = 0
    for prompt_id, image in _read(record).items():
        try:
            history = client.fetch_history(prompt_id)
            if not history:
                client.cancel_prompt(prompt_id)
                client.interrupt(prompt_id)
                continue
        except Exception as e:
            logger.warning("Could not ask ComfyUI about image look-over %s: %s", prompt_id, e)
            continue
        places = points_of_interest.reported(history.get("outputs", {}), parts_found_by(history))
        if places is not None and _keep(db, image.get("row"), image.get("file"), places):
            folded += 1
    record.unlink(missing_ok=True)
    if folded:
        logger.info("Kept the places found in %d image(s) while the app was closed", folded)
    return folded


def _keep(db, row_id, filename, places: list[dict]) -> bool:
    row = db.get_generation(row_id) if row_id else None
    files = gallery.row_output_files(row) if row is not None else []
    entry = next((f for f in files if f.get("filename") == filename), None)
    if entry is None:
        return False
    entry.update(points_of_interest.kept(places))
    db.update_generation(row_id, output_files=json.dumps(files))
    return True


def _read(record: Path) -> dict:
    try:
        written = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return written if isinstance(written, dict) else {}


def _write(record: Path, waiting: dict) -> None:
    partial = record.with_name(f"{record.name}.partial")
    partial.write_text(json.dumps(waiting, indent=1), encoding="utf-8", newline="\n")
    partial.replace(record)


def finding_graph(version: gallery.EnhanceVersion) -> dict:
    graph = {_IMAGE: {"class_type": "LoadImage", "inputs": {"image": _reference_to(version)}}}
    for index, fix in enumerate(detail_fix_passes(version.params)):
        graph.update(finding_nodes(index, fix, [_IMAGE, 0], [_IMAGE, 0])[0])
    return graph


def _reference_to(version: gallery.EnhanceVersion) -> str | None:
    return gallery.output_file_reference([version.file])


def images_to_look_over(rows: list[dict]) -> list[tuple[dict, gallery.EnhanceVersion]]:
    return [(row, version) for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE
            for version in gallery.enhancement_versions(row)
            if not version.is_original and not points_of_interest.kept_the_current_way(version.file)
            and detail_fix_passes(version.params)]
