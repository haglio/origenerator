from __future__ import annotations

import logging
from pathlib import Path

from origenerator.completion import extract_completion, mark_generation_completed
from origenerator.gallery.output import is_in_progress
from origenerator.gallery.signatures import parse_params
from origenerator.generation_state import GenerationSource, GenerationStatus, source_of
from origenerator.library_filing import saved_in_its_run_folder
from origenerator.output_places import OutputPlaces
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


def drop_in_flight(db, client, source: str, noun: str) -> int:
    dropped = 0
    for row in db.list_generations():
        if row.get("source") != source or not is_in_progress(row):
            continue
        prompt_id = row["prompt_id"]
        try:
            client.cancel_prompt(prompt_id)
            client.interrupt(prompt_id)
        except Exception as e:
            logger.warning("Could not dequeue %s %s: %s", noun, prompt_id, e)
            continue
        db.delete_generation(prompt_id)
        dropped += 1
    if dropped:
        logger.info("Dropped %d queued %s(s) — the app is open", dropped, noun)
    return dropped


def reconcile_in_flight(db, client, places: OutputPlaces, thumb_dir: Path) -> dict:
    return _reconcile(db, client, [r for r in db.list_generations()
                                   if r.get("status") == GenerationStatus.RUNNING],
                      places, thumb_dir, "in-flight generations")


def reconcile_the_backfill(db, client, places: OutputPlaces, thumb_dir: Path) -> dict:
    waiting_or_running = [r for r in db.list_generations()
                          if source_of(r) == GenerationSource.BACKFILL and is_in_progress(r)]
    return _reconcile(db, client, waiting_or_running, places, thumb_dir, "the backfill's runs")


def _reconcile(db, client, rows: list[dict], places: OutputPlaces, thumb_dir: Path,
               what: str) -> dict:
    summary = {"finalized": 0, "running": 0, "cleared": 0}
    if not rows:
        return summary
    try:
        queued = client.fetch_queue()
    except Exception as e:
        logger.warning("Could not read ComfyUI queue; leaving in-flight rows as-is: %s", e)
        summary["running"] = len(rows)
        return summary

    for row in rows:
        summary[_reconcile_row(db, client, row, queued, places, thumb_dir)] += 1
    logger.info(
        "Reconciled %s: %d finalized, %d still running, %d cleared",
        what, summary["finalized"], summary["running"], summary["cleared"],
    )
    return summary


def take_in_what_landed(db, client, row, places: OutputPlaces, thumb_dir: Path) -> bool:
    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
    history = _safe_history(client, row["prompt_id"]) if workflow is not None else {}
    return _record(db, row, workflow, history, places, thumb_dir)


def take_in_what_its_folder_holds(db, row, places: OutputPlaces, thumb_dir: Path) -> bool:
    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
    saved = saved_in_its_run_folder(parse_params(row.get("workflow_json")), places,
                                    row["prompt_id"])
    return _record(db, row, workflow, saved, places, thumb_dir)


def _record(db, row, workflow, history: dict, places: OutputPlaces, thumb_dir: Path) -> bool:
    if workflow is None or not history:
        return False
    prompt_id = row["prompt_id"]
    files, thumb, duration = extract_completion(
        workflow, history, places, thumb_dir, prompt_id,
        params=parse_params(row.get("params_json")))
    if not files:
        return False
    mark_generation_completed(db, prompt_id, files, thumb, duration)
    return True


def _reconcile_row(db, client, row, queued, places: OutputPlaces, thumb_dir: Path) -> str:
    if take_in_what_landed(db, client, row, places, thumb_dir):
        return "finalized"
    if row["prompt_id"] in queued:
        return "running"
    if take_in_what_its_folder_holds(db, row, places, thumb_dir):
        return "finalized"
    db.delete_generation(row["prompt_id"])
    return "cleared"


def _safe_history(client, prompt_id: str) -> dict:
    try:
        return client.fetch_history(prompt_id)
    except Exception as e:
        logger.warning("Could not fetch history for %s: %s", prompt_id, e)
        return {}
