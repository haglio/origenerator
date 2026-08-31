"""Resolve generations left in flight by a previous session against ComfyUI.

A job Origenerator hands ComfyUI keeps running there after the app closes, so on
the next launch each still-``running`` DB row is checked against the server it
was submitted to — matched by the shared prompt_id — and:

  - **finished while we were away** → finalized from ``/history`` (its outputs,
    thumbnail and duration), so it shows as a real result instead of a job stuck
    forever at "generating";
  - **still queued or executing** → left as-is, for the UI to reconnect to live;
  - **gone** (ComfyUI restarted, or the job was dropped) → the stale row is
    deleted; any file it managed to write is picked up by the normal disk import.

Runs before the importer so a finalized row's output is already recorded and is
not imported a second time. Never raises: if ComfyUI can't be read, in-flight
rows are left untouched for a later launch to resolve.

The only startup reconcile that needs a ComfyUI client; the bookmark reconciles
are :mod:`origenerator.bookmark_reconcile`, and share nothing with this but the
word.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from origenerator.completion import extract_completion
from origenerator.gallery.signatures import parse_params
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# The status of a row whose prompt ComfyUI was given. A ``pending`` row is the
# other kind of in-flight: one the queue was still holding when the app closed,
# which the server has never heard of and cannot be asked about — the app takes
# those back itself (see :meth:`RerollController.reconnect_running`), so checking
# them here would only delete a queue the user is still waiting on.
_SENT = ("running",)


def reconcile_in_flight(db, client, output_dir: Path, thumb_dir: Path) -> dict:
    """Reconcile every submitted-and-unfinished DB row against ``client`` (ComfyUI).

    Returns a summary ``{"finalized": n, "running": n, "cleared": n}``.
    """
    rows = [r for r in db.list_generations() if r.get("status") in _SENT]
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
        summary[_reconcile_row(db, client, row, queued, output_dir, thumb_dir)] += 1
    logger.info(
        "Reconciled in-flight generations: %d finalized, %d still running, %d cleared",
        summary["finalized"], summary["running"], summary["cleared"],
    )
    return summary


def _reconcile_row(db, client, row, queued, output_dir: Path, thumb_dir: Path) -> str:
    prompt_id = row["prompt_id"]
    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
    history = _safe_history(client, prompt_id)
    if workflow is not None and history:
        files, thumb, duration = extract_completion(
            workflow, history, output_dir, thumb_dir, prompt_id,
            params=parse_params(row.get("params_json")),
        )
        if files:
            fields = dict(
                status="completed",
                output_files=json.dumps(files),
                thumbnail_path=thumb,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            if duration is not None:
                fields["duration_seconds"] = duration
            db.update_generation(prompt_id, **fields)
            return "finalized"
    if prompt_id in queued:
        return "running"  # still in flight; leave it for the UI to reconnect to
    db.delete_generation(prompt_id)  # gone from the server with no output recorded
    return "cleared"


def _safe_history(client, prompt_id: str) -> dict:
    try:
        return client.fetch_history(prompt_id)
    except Exception as e:
        logger.warning("Could not fetch history for %s: %s", prompt_id, e)
        return {}
