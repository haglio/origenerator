"""Resolve generations left in flight by a previous session against ComfyUI.

A job Origenerator launches keeps running inside ComfyUI after the app closes,
so on the next launch each still-``running`` (or ``pending``) DB row is checked
against the server it was submitted to — matched by the shared prompt_id — and:

  - **finished while we were away** → finalized from ``/history`` (its outputs,
    thumbnail and duration), so it shows as a real result instead of a job stuck
    forever at "generating";
  - **still queued or executing** → left as-is, for the UI to reconnect to live;
  - **gone** (ComfyUI restarted, or the job was dropped) → the stale row is
    deleted; any file it managed to write is picked up by the normal disk import.

Runs before the importer so a finalized row's output is already recorded and is
not imported a second time. Never raises: if ComfyUI can't be read, in-flight
rows are left untouched for a later launch to resolve.

Also home to :func:`reconcile_folder_meta`, the other startup reconcile: it heals
gallery bookmarks (stars and custom names) whose folder key drifted after a key
formula changed, and stamps each live bookmark with the identity needed to survive
the next such change.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from origenerator import gallery
from origenerator.completion import extract_completion
from origenerator.gallery.signatures import parse_params
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# Statuses a row can carry while its ComfyUI job is unfinished. ``pending`` is the
# insert-time default that a crash can freeze a row at before it reaches ``running``.
_IN_FLIGHT = ("running", "pending")


def reconcile_in_flight(db, client, output_dir: Path, thumb_dir: Path) -> dict:
    """Reconcile every in-flight DB row against ``client`` (ComfyUI).

    Returns a summary ``{"finalized": n, "running": n, "cleared": n}``.
    """
    rows = [r for r in db.list_generations() if r.get("status") in _IN_FLIGHT]
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


def reconcile_folder_meta(db) -> dict:
    """Re-point gallery bookmarks whose folder key no longer matches a folder, and
    stamp identity onto the ones that still do.

    A bookmark (a star or custom name) is keyed by a hash of its folder's settings;
    when a key formula changes, that key stops matching and the bookmark silently
    detaches. On startup, for each ``folder_meta`` row:

      - **key still matches a folder** → refresh its stored ``(level, ref)`` so a
        future formula change can re-derive it from a member generation;
      - **key dangles, stored ref still exists** → recompute the key at the stored
        tier and move the bookmark onto it (robust to *any* formula change);
      - **key dangles, no usable identity** → try the one legacy settings formula
        to find its folder (recovers bookmarks predating stored identity);
      - **still nothing** → leave it alone; its generations are gone, and a user's
        star or name is never dropped.

    Returns ``{"refreshed": n, "repointed": n, "orphaned": n}``.
    """
    meta = db.folder_meta_full()
    summary = {"refreshed": 0, "repointed": 0, "orphaned": 0}
    if not meta:
        return summary
    rows_by_id = {r["prompt_id"]: r for r in db.list_generations()}
    image_index = gallery.build_image_config_index(
        [r for r in rows_by_id.values() if gallery.media_type_of_row(r) == "image"]
    )
    current, legacy_keys = _index_current_folders(rows_by_id.values(), image_index)
    meta_by_key = {m["folder_key"]: dict(m) for m in meta}

    for row in meta:
        key = row["folder_key"]
        if key in current:
            level, ref = current[key]
            if (row["level"], row["ref_prompt_id"]) != (level, ref):
                cur = meta_by_key[key]
                db.upsert_folder_meta(key, custom_name=cur["custom_name"],
                                      starred=cur["starred"], level=level, ref_prompt_id=ref)
                cur["level"], cur["ref_prompt_id"] = level, ref
                summary["refreshed"] += 1
            continue
        target = _repoint_target(row, current, rows_by_id, legacy_keys, image_index)
        if target is None:
            summary["orphaned"] += 1
            continue
        _move_bookmark(db, row, target, current[target], meta_by_key)
        summary["repointed"] += 1

    logger.info("Reconciled folder bookmarks: %(refreshed)d refreshed, "
                "%(repointed)d re-pointed, %(orphaned)d orphaned", summary)
    return summary


def _index_current_folders(rows, image_index):
    """Map every current folder key → ``(level, a member prompt_id)``, plus each
    settings folder's legacy keys → its current key (for the historical formula
    changes, so bookmarks made before stored identity can still be recovered)."""
    current: dict = {}
    legacy_keys: dict = {}

    def walk(groups):
        for group in groups:
            members = gallery.rows_under(group)
            if members:
                current[group.key] = (gallery.group_level(group), members[0]["prompt_id"])
                if isinstance(group, gallery.SettingsGroup):
                    for legacy in (
                        gallery.legacy_settings_folder_key(members[0]),
                        gallery.legacy_preframe_settings_folder_key(members[0]),
                        gallery.legacy_preversion_settings_folder_key(members[0], image_index),
                        # Per member, not just the first: the enhancement split
                        # merged two folders into this one, and a star on either
                        # of them has to find its way here.
                        *gallery.legacy_preenhance_settings_folder_keys(members, image_index),
                    ):
                        if legacy != group.key:
                            legacy_keys.setdefault(legacy, group.key)
            walk(gallery.child_groups(group))

    walk(gallery.build_gallery_tree(list(rows), {}))
    return current, legacy_keys


def _repoint_target(row, current, rows_by_id, legacy_keys, image_index):
    """The current key a dangling bookmark should move to, or ``None``.

    Prefers recomputing from the bookmark's stored identity — a member row at its
    tier, robust to any formula change — and falls back to a legacy settings
    formula for bookmarks that predate stored identity."""
    ref, level = row["ref_prompt_id"], row["level"]
    if ref and level and ref in rows_by_id:
        candidate = gallery.folder_key_at_level(rows_by_id[ref], level, image_index)
        if candidate in current:
            return candidate
    return legacy_keys.get(row["folder_key"])


def _move_bookmark(db, row, target, identity, meta_by_key):
    """Move a bookmark's star/name onto ``target`` (merging into any bookmark
    already there — a name and a star both survive), then drop its stale key."""
    level, ref = identity
    existing = meta_by_key.get(target)
    name = (existing["custom_name"] if existing else None) or row["custom_name"]
    starred = bool((existing["starred"] if existing else False) or row["starred"])
    db.upsert_folder_meta(target, custom_name=name, starred=starred,
                          level=level, ref_prompt_id=ref)
    db.delete_folder_meta(row["folder_key"])
    meta_by_key[target] = {"folder_key": target, "custom_name": name, "starred": starred,
                           "level": level, "ref_prompt_id": ref}
    meta_by_key.pop(row["folder_key"], None)
