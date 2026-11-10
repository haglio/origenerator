from __future__ import annotations

import json
import logging
import statistics
import time
import uuid

from origenerator import gallery
from origenerator.completion import extract_completion
from origenerator.config import OUTPUT_PLACES, THUMB_DIR
from origenerator.gallery.output import is_in_progress
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.inflight import drop_in_flight
from origenerator.library_filing import saving_into_its_run_folder
from origenerator.media import MediaType
from origenerator.output_places import OutputFolders
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

BATCH_MINUTES = 45.0

UNTIMED_SECONDS = 60.0

TARGET_KEY = "_base_render_of"


def rows_missing_their_base(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        if row.get("source") == GenerationSource.BASE_RENDER:
            continue
        if gallery.media_type_of_row(row) != MediaType.IMAGE:
            continue
        if not gallery.is_enhanced_row(row) or gallery.original_files_of(row):
            continue
        if not gallery.produced_output(row):
            continue
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or "enhance" not in workflow.default_params():
            continue
        out.append(row)
    return out


def base_params_for(row: dict, workflow) -> dict:
    params = dict(workflow.default_params())
    params.update(gallery.parse_params(row.get("params_json")))
    params["enhance"] = False
    params[TARGET_KEY] = row["prompt_id"]
    return params


def already_queued(rows: list[dict]) -> set[str]:
    return {
        gallery.parse_params(r.get("params_json")).get(TARGET_KEY)
        for r in rows if r.get("source") == GenerationSource.BASE_RENDER and is_in_progress(r)
    } - {None}


def typical_seconds(rows: list[dict], workflow_name: str) -> float:
    timed = [
        row["duration_seconds"] for row in rows
        if row.get("workflow_name") == workflow_name
        and row.get("status") == GenerationStatus.COMPLETED
        and row.get("duration_seconds")
    ]
    return statistics.median(timed) if timed else UNTIMED_SECONDS


def queue_base_renders(rows: list[dict], launch, limit: int | None = None,
                       budget_minutes: float = BATCH_MINUTES) -> int:
    pending = already_queued(rows)

    def launch_one(row: dict) -> bool:
        workflow = WORKFLOW_REGISTRY[row["workflow_name"]]
        return launch(workflow, base_params_for(row, workflow)) is not None

    queued, spent = queue_within_budget(
        rows, [row for row in rows_missing_their_base(rows) if row["prompt_id"] not in pending],
        launch_one, budget_minutes=budget_minutes, limit=limit)
    if queued:
        logger.info("Queued %d base re-render(s) (~%d min) to run while the app "
                    "is closed", queued, round(spent / 60))
    return queued


def queue_within_budget(rows: list[dict], candidates: list[dict], launch_one, *,
                        budget_minutes: float, limit: int | None = None) -> tuple[int, float]:
    cost: dict[str, float] = {}
    budget = budget_minutes * 60
    spent = 0.0
    queued = 0
    for row in candidates:
        if limit is not None and queued >= limit:
            break
        name = row["workflow_name"]
        if name not in cost:
            cost[name] = typical_seconds(rows, name)
        if queued and spent + cost[name] > budget:
            break
        if launch_one(row):
            queued += 1
            spent += cost[name]
    return queued, spent


RENDER_POLL_SECONDS = 2.0
ONE_IMAGE_ON_ANY_MODEL_SECONDS = 900


def render_base_now(client, workflow, params: dict, *,
                    now=time.monotonic, sleep=time.sleep) -> list[dict]:
    prompt_id = str(uuid.uuid4())
    client.submit_job(
        saving_into_its_run_folder(workflow.payload_for_comfyui(params), OUTPUT_PLACES, prompt_id),
        prompt_id)
    deadline = now() + ONE_IMAGE_ON_ANY_MODEL_SECONDS
    while now() < deadline:
        sleep(RENDER_POLL_SECONDS)
        history = client.fetch_history(prompt_id)
        if not history:
            continue
        files, _thumb, _duration = extract_completion(
            workflow, history, OutputFolders(OUTPUT_PLACES, THUMB_DIR), prompt_id,
            params=params,
        )
        return files
    logger.warning("Base re-render %s did not land within %ss",
                   prompt_id, ONE_IMAGE_ON_ANY_MODEL_SECONDS)
    return []


def attach_base(db, target_id: str, files: list[dict]) -> bool:
    target = db.get_generation(target_id) if target_id else None
    if not files or target is None or gallery.original_files_of(target):
        return False
    base = [dict(f, role="original") for f in files]
    db.update_generation(
        target_id,
        output_files=json.dumps(gallery.row_output_files(target) + base),
        original_files=json.dumps(base),
    )
    logger.info("Folded a re-derived base render into %s", target_id)
    return True


def fold_base_render(db, render_row: dict) -> str | None:
    target_id = gallery.parse_params(render_row.get("params_json")).get(TARGET_KEY)
    if not attach_base(db, target_id, gallery.row_output_files(render_row)):
        return None
    db.delete_generation(render_row["prompt_id"])
    return target_id


def fold_completed_base_renders(db) -> int:
    folded = 0
    for row in db.list_generations():
        if (row.get("source") != GenerationSource.BASE_RENDER
                or row.get("status") != GenerationStatus.COMPLETED):
            continue
        if fold_base_render(db, row) is not None:
            folded += 1
    if folded:
        logger.info("Folded %d base render(s) from the last absence", folded)
    return folded


def cancel_base_renders(db, client) -> int:
    return drop_in_flight(db, client, GenerationSource.BASE_RENDER, "base re-render")
