"""Finding the places in pictures enhanced before the places were kept, while the app is shut.

Only each Fix's finding runs (:mod:`origenerator.workflows.fix_finding`), with the detectors that
picture's own enhancement used and nothing redrawn, so it is a second or two of ComfyUI per
picture. It rides the absence the base re-renders ride: queued as the app closes, folded into the
pictures at the next launch, and whatever had not run by then taken back off ComfyUI."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from origenerator import gallery, points_of_interest
from origenerator.branch_session import is_branch_session
from origenerator.config import LIBRARY_STATE_DIR
from origenerator.media import MediaType
from origenerator.workflows.detail_parts import detail_fix_passes
from origenerator.workflows.fix_finding import finding_nodes, parts_found_by

logger = logging.getLogger(__name__)

RUNS_PER_ABSENCE = 600
RECORD = LIBRARY_STATE_DIR / "pictures_being_looked_over.json"
_PICTURE = "picture"


def queue_finding_for_the_absence(db, client) -> int:
    if is_branch_session() or client is None:
        return 0
    return queue_finding(db.list_generations(), client, RECORD)


def queue_finding(rows: list[dict], client, record: Path, limit: int = RUNS_PER_ABSENCE) -> int:
    waiting = _read(record)
    asked = {(one["row"], one["file"]) for one in waiting.values()}
    queued = 0
    for row, level in pictures_to_look_over(rows):
        if queued >= limit:
            break
        picture = (row["prompt_id"], level.file["filename"])
        if picture in asked:
            continue
        prompt_id = str(uuid.uuid4())
        try:
            client.submit_job(finding_graph(level), prompt_id)
        except Exception as e:
            logger.warning("ComfyUI took no more pictures to look over: %s", e)
            break
        waiting[prompt_id] = {"row": picture[0], "file": picture[1]}
        queued += 1
    _write(record, waiting)
    if queued:
        logger.info("Queued %d picture(s) to look over for their places while the app is closed", queued)
    return queued


def fold_found_places(db, client, record: Path) -> int:
    folded = 0
    for prompt_id, picture in _read(record).items():
        try:
            history = client.fetch_history(prompt_id)
            if not history:
                client.cancel_prompt(prompt_id)
                client.interrupt(prompt_id)
                continue
        except Exception as e:
            logger.warning("Could not ask ComfyUI about picture look-over %s: %s", prompt_id, e)
            continue
        places = points_of_interest.reported(history.get("outputs", {}), parts_found_by(history))
        if places is not None and _keep(db, picture.get("row"), picture.get("file"), places):
            folded += 1
    record.unlink(missing_ok=True)
    if folded:
        logger.info("Kept the places found in %d picture(s) while the app was closed", folded)
    return folded


def _keep(db, row_id, filename, places: list[dict]) -> bool:
    row = db.get_generation(row_id) if row_id else None
    files = gallery.row_output_files(row) if row is not None else []
    entry = next((f for f in files if f.get("filename") == filename), None)
    if entry is None:
        return False
    entry[points_of_interest.FILE_KEY] = places
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


def finding_graph(level: gallery.EnhanceLevel) -> dict:
    graph = {_PICTURE: {"class_type": "LoadImage",
                        "inputs": {"image": gallery.output_file_reference([level.file])}}}
    for index, (detector, _denoise) in enumerate(detail_fix_passes(level.params)):
        graph.update(finding_nodes(index, detector, [_PICTURE, 0], [_PICTURE, 0])[0])
    return graph


def pictures_to_look_over(rows: list[dict]) -> list[tuple[dict, gallery.EnhanceLevel]]:
    return [(row, level) for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE
            for level in gallery.enhance_levels(row)
            if not level.is_original and _unlooked(level.file) and detail_fix_passes(level.params)]


def _unlooked(file_entry: dict) -> bool:
    places = file_entry.get(points_of_interest.FILE_KEY)
    return places is None or any(not isinstance(place, dict) or "part" not in place for place in places)
