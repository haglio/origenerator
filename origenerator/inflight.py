"""Resolve generations left in flight by a previous session against ComfyUI.

A job Origenerator hands ComfyUI keeps running there after the app closes, so on
the next launch each still-``running`` DB row is checked against the server it
was submitted to — matched by the shared prompt_id — and:

  - **finished while we were away** → finalized from ``/history`` (its outputs,
    thumbnail and duration), so it shows as a real result instead of a job stuck
    forever at "generating";
  - **still queued or executing** → left as-is, for the UI to reconnect to live;
  - **gone** (ComfyUI forgets every run when it restarts) → finalized from what
    it saved in its own folder, or deleted when it saved nothing there.

Never raises: if ComfyUI can't be read, in-flight rows are left untouched for a
later launch to resolve.

The only startup reconcile that needs to reach ComfyUI at all; the bookmark
reconciles are :mod:`origenerator.bookmark_reconcile`, and share nothing with
this but the word. What it needs is the REST surface --
:class:`~origenerator.comfyui_api.ComfyUIApi`, which loads no Qt -- and a
``ComfyUIClient`` forwards every call of it, so either can be handed in.
"""
from __future__ import annotations

import logging
from pathlib import Path

from origenerator.completion import extract_completion, mark_generation_completed
from origenerator.gallery.output import is_in_progress
from origenerator.gallery.signatures import parse_params
from origenerator.generation_state import GenerationStatus
from origenerator.library_filing import saved_in_its_run_folder
from origenerator.output_places import OutputPlaces
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


def drop_in_flight(db, client, source: str, noun: str) -> int:
    """Take the unfinished rows of ``source`` off ComfyUI and out of the
    database, and say how many went.

    What opening the app does with the work an absence queued: the GPU is the
    user's again. Each row is dequeued and asked to stop by name; which one the
    server is executing only it knows, since a ``running`` row was handed over,
    not necessarily started. A row the server would not let go of is kept: the
    prompt may still run, and the app adopts an in-flight row as a live job the
    user's work can preempt. Finished rows are untouched.
    """
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
    """Reconcile every submitted-and-unfinished DB row against ``client`` (ComfyUI).

    Returns a summary ``{"finalized": n, "running": n, "cleared": n}``.
    """
    # Only rows whose prompt ComfyUI was given. A ``pending`` row is the other
    # kind of in-flight: one the queue was still holding when the app closed,
    # which the server has never heard of and cannot be asked about — the app
    # takes those back itself (see :meth:`JobQueue.reconnect_running`),
    # so checking them here would only delete a queue the user is still waiting on.
    rows = [r for r in db.list_generations()
            if r.get("status") == GenerationStatus.RUNNING]
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
        "Reconciled in-flight generations: %d finalized, %d still running, %d cleared",
        summary["finalized"], summary["running"], summary["cleared"],
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
        return "running"  # still in flight; leave it for the UI to reconnect to
    if take_in_what_its_folder_holds(db, row, places, thumb_dir):
        return "finalized"
    db.delete_generation(row["prompt_id"])  # gone from the server with no output recorded
    return "cleared"


def _safe_history(client, prompt_id: str) -> dict:
    try:
        return client.fetch_history(prompt_id)
    except Exception as e:
        logger.warning("Could not fetch history for %s: %s", prompt_id, e)
        return {}
