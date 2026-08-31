"""Heal the gallery bookmarks a folder-key formula change detached.

A gallery folder has no id: its key is derived from the settings its generations
share, so a change to that formula silently detaches every bookmark keyed by the
old one — a star, a name the user typed, a folder they gathered by hand. Both
tables that hold such a key are reconciled at startup, and both the same way,
for each stored key:

  - **still matches a folder** → refresh its stored ``(level, ref)`` so a future
    formula change can re-derive it from a member generation;
  - **dangles, stored ref still exists** → recompute the key at the stored tier
    and move the bookmark onto it (robust to *any* formula change);
  - **dangles, no usable identity** → try the legacy settings formulas, which
    recovers bookmarks predating stored identity;
  - **still nothing** → leave it alone. Its generations are gone, and a user's
    star, name or grouping is never dropped.

Both after the backfills, because a backfill can move a generation's folder by
filling in its workflow, model or LoRA, so the tree they reconcile against has
to be final. The other startup reconcile — resolving in-flight generations
against ComfyUI — is :mod:`origenerator.inflight`, and shares nothing with this
but the word.
"""

import logging
from dataclasses import dataclass

from origenerator import gallery

logger = logging.getLogger(__name__)

_NOTHING = {"refreshed": 0, "repointed": 0, "orphaned": 0}


@dataclass(frozen=True)
class Folders:
    """One reading of the gallery tree, indexed the ways a reconcile needs it.

    Built once and used by both passes. Safe to share because neither writes to
    `generations` — both write only to the bookmark tables — so the tree the
    second reconciles against is the tree the first did. tests/test_reconcile.py
    asserts that, since sharing it is what makes the assumption load-bearing.
    """

    #: folder key → ``(level, a member prompt_id)``, for every folder there is.
    current: dict
    #: a settings folder's keys under older formulas → its key today.
    legacy_keys: dict
    #: every generation by prompt id, which is what a stored ref resolves to.
    rows_by_id: dict
    #: the image-config index the key formulas need.
    image_index: dict


def index_folders(db) -> Folders:
    """Read the whole gallery tree once, and index it for both passes."""
    rows_by_id = {r["prompt_id"]: r for r in db.list_generations()}
    image_index = gallery.build_image_config_index(
        [r for r in rows_by_id.values() if gallery.media_type_of_row(r) == "image"]
    )
    current, legacy_keys = _index_current_folders(rows_by_id.values(), image_index)
    return Folders(current, legacy_keys, rows_by_id, image_index)


def reconcile_bookmarks(db) -> dict:
    """Both bookmark passes, over one reading of the gallery tree.

    Ordered: the stars and names first, then the folders the user composed by
    hand. Returns each pass's summary under its own key.
    """
    if not db.folder_meta_full() and not db.custom_folder_members_full():
        return {"folder_meta": dict(_NOTHING), "custom_folders": dict(_NOTHING)}
    folders = index_folders(db)
    return {
        "folder_meta": reconcile_folder_meta(db, folders),
        "custom_folders": reconcile_custom_folders(db, folders),
    }


def reconcile_folder_meta(db, folders: Folders | None = None) -> dict:
    """Re-point stars and custom names whose folder key no longer matches.

    Returns ``{"refreshed": n, "repointed": n, "orphaned": n}``.
    """
    meta = db.folder_meta_full()
    if not meta:
        return dict(_NOTHING)
    folders = index_folders(db) if folders is None else folders
    meta_by_key = {m["folder_key"]: dict(m) for m in meta}

    def refresh(row, identity):
        level, ref = identity
        held = meta_by_key[row["folder_key"]]
        db.upsert_folder_meta(row["folder_key"], custom_name=held["custom_name"],
                              starred=held["starred"], level=level, ref_prompt_id=ref)
        held["level"], held["ref_prompt_id"] = level, ref

    def repoint(row, target, identity):
        _move_bookmark(db, row, target, identity, meta_by_key)

    summary = _reconcile_keys(meta, folders, refresh, repoint)
    logger.info("Reconciled folder bookmarks: %(refreshed)d refreshed, "
                "%(repointed)d re-pointed, %(orphaned)d orphaned", summary)
    return summary


def reconcile_custom_folders(db, folders: Folders | None = None) -> dict:
    """Re-point custom-folder memberships whose folder key no longer matches.

    A custom folder gathers folders by key, so it drifts exactly the way a star
    does — and a grouping the user built by hand is worth no less than a star.

    Returns ``{"refreshed": n, "repointed": n, "orphaned": n}``.
    """
    members = db.custom_folder_members_full()
    if not members:
        return dict(_NOTHING)
    folders = index_folders(db) if folders is None else folders

    def refresh(member, identity):
        level, ref = identity
        db.stamp_custom_folder_member(member["folder_id"], member["folder_key"],
                                      level=level, ref_prompt_id=ref)

    def repoint(member, target, identity):
        level, ref = identity
        db.repoint_custom_folder_member(member["folder_id"], member["folder_key"],
                                        target, level=level, ref_prompt_id=ref)

    summary = _reconcile_keys(members, folders, refresh, repoint)
    logger.info("Reconciled custom folders: %(refreshed)d refreshed, "
                "%(repointed)d re-pointed, %(orphaned)d orphaned", summary)
    return summary


def _reconcile_keys(rows, folders: Folders, refresh, repoint) -> dict:
    """The three-outcome pass both tables get, with the writes handed in.

    *refresh* takes ``(row, identity)`` and *repoint* ``(row, target, identity)``,
    where an identity is the ``(level, member prompt_id)`` of a folder that is
    there today. Everything else — which key is live, which dangles, and where a
    dangling one belongs — is the same question for a star and for a membership.
    """
    summary = dict(_NOTHING)
    for row in rows:
        key = row["folder_key"]
        if key in folders.current:
            identity = folders.current[key]
            if (row["level"], row["ref_prompt_id"]) != identity:
                refresh(row, identity)
                summary["refreshed"] += 1
            continue
        target = _repoint_target(row, folders)
        if target is None:
            summary["orphaned"] += 1
            continue
        repoint(row, target, folders.current[target])
        summary["repointed"] += 1
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


def _repoint_target(row, folders: Folders):
    """The current key a dangling bookmark should move to, or ``None``.

    Prefers recomputing from the bookmark's stored identity — a member row at its
    tier, robust to any formula change — and falls back to a legacy settings
    formula for bookmarks that predate stored identity."""
    ref, level = row["ref_prompt_id"], row["level"]
    if ref and level and ref in folders.rows_by_id:
        candidate = gallery.folder_key_at_level(
            folders.rows_by_id[ref], level, folders.image_index)
        if candidate in folders.current:
            return candidate
    return folders.legacy_keys.get(row["folder_key"])


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
