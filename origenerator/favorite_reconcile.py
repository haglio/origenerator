from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from functools import cached_property

from origenerator import gallery
from origenerator.gallery.shapes import LANDSCAPE, PORTRAIT
from origenerator.item_shape import row_shape
from origenerator.media import MediaType

logger = logging.getLogger(__name__)

_NOTHING = {"refreshed": 0, "repointed": 0, "orphaned": 0}


@dataclass(frozen=True)
class Folders:
    current: dict
    rows_by_id: dict
    image_index: dict
    tree: list

    @cached_property
    def legacy_keys(self) -> dict:
        return _legacy_keys(self.tree, self.image_index)


def index_folders(db) -> Folders:
    rows_by_id = {r["prompt_id"]: r for r in db.list_generations()}
    image_index = gallery.build_image_config_index(
        [r for r in rows_by_id.values() if gallery.media_type_of_row(r) == MediaType.IMAGE]
    )
    tree = gallery.build_gallery_tree(list(rows_by_id.values()), {})
    current = {group.key: (gallery.group_level(group), folder_rows[0]["prompt_id"])
               for group, folder_rows in _folders_holding_rows(tree)}
    return Folders(current, rows_by_id, image_index, tree)


def reconcile_favorites(db) -> dict:
    if not db.folder_meta_full() and not db.folders_in_custom_collections():
        return {"folder_meta": dict(_NOTHING), "custom_folders": dict(_NOTHING),
                "custom_collection_shapes": 0}
    folders = index_folders(db)
    return {
        "folder_meta": reconcile_folder_meta(db, folders),
        "custom_folders": reconcile_custom_collections(db, folders),
        "custom_collection_shapes": stamp_custom_collection_shapes(db, folders),
    }


def reconcile_folder_meta(db, folders: Folders | None = None) -> dict:
    meta = db.folder_meta_full()
    if not meta:
        return dict(_NOTHING)
    folders = index_folders(db) if folders is None else folders
    meta_by_key = {m["folder_key"]: dict(m) for m in meta}

    def refresh(row, identity):
        level, ref = identity
        held = meta_by_key[row["folder_key"]]
        db.upsert_folder_meta(row["folder_key"], custom_name=held["custom_name"],
                              favorite=held["starred"], level=level, ref_prompt_id=ref)
        held["level"], held["ref_prompt_id"] = level, ref

    def repoint(row, target, identity):
        _move_favorite(db, row, target, identity, meta_by_key)

    summary = _reconcile_keys(meta, folders, refresh, repoint)
    logger.info("Reconciled folder favorites: %(refreshed)d refreshed, "
                "%(repointed)d re-pointed, %(orphaned)d orphaned", summary)
    return summary


def reconcile_custom_collections(db, folders: Folders | None = None) -> dict:
    gathered = [held for held in db.folders_in_custom_collections()
                if gallery.custom_folder_id(held["folder_key"]) is None]
    if not gathered:
        return dict(_NOTHING)
    folders = index_folders(db) if folders is None else folders

    def refresh(held, identity):
        level, ref = identity
        db.stamp_folder_in_custom_collection(held["folder_id"], held["folder_key"],
                                         level=level, ref_prompt_id=ref)

    def repoint(held, target, identity):
        level, ref = identity
        db.repoint_folder_in_custom_collection(held["folder_id"], held["folder_key"],
                                           target, level=level, ref_prompt_id=ref)

    summary = _reconcile_keys(gathered, folders, refresh, repoint)
    logger.info("Reconciled custom collections: %(refreshed)d refreshed, "
                "%(repointed)d re-pointed, %(orphaned)d orphaned", summary)
    return summary


def stamp_custom_collection_shapes(db, folders: Folders | None = None) -> int:
    unshaped = [record for record in db.list_custom_collections() if record["side"] is None]
    if not unshaped:
        return 0
    folders = index_folders(db) if folders is None else folders
    for folder in gallery.build_custom_collections(folders.tree, unshaped):
        shapes = Counter(row_shape(row) for row in gallery.rows_under(folder))
        db.set_custom_collection_shape(
            folder.folder_id, PORTRAIT if shapes[PORTRAIT] > shapes[LANDSCAPE] else LANDSCAPE)
    logger.info("Put %d custom collection(s) on a side", len(unshaped))
    return len(unshaped)


def _reconcile_keys(rows, folders: Folders, refresh, repoint) -> dict:
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


def _folders_holding_rows(groups):
    for group in groups:
        folder_rows = gallery.rows_under(group)
        if folder_rows:
            yield group, folder_rows
        yield from _folders_holding_rows(gallery.child_groups(group))


def _legacy_keys(tree, image_index) -> dict:
    legacy_keys: dict = {}
    for group, folder_rows in _folders_holding_rows(tree):
        if isinstance(group, gallery.SettingsGroup):
            for legacy in (
                gallery.legacy_settings_folder_key(folder_rows[0]),
                gallery.legacy_preframe_settings_folder_key(folder_rows[0]),
                gallery.legacy_preversion_settings_folder_key(folder_rows[0], image_index),
                *gallery.legacy_preenhance_settings_folder_keys(folder_rows, image_index),
            ):
                if legacy != group.key:
                    legacy_keys.setdefault(legacy, group.key)
        if isinstance(group, (gallery.LoraGroup, gallery.SourceImageGroup)):
            legacy_keys.setdefault(gallery.legacy_parentless_folder_key(
                folder_rows[0], group.level, image_index), group.key)
    return legacy_keys


def _repoint_target(row, folders: Folders):
    ref, level = row["ref_prompt_id"], row["level"]
    if ref and level and ref in folders.rows_by_id:
        candidate = gallery.folder_key_at_level(
            folders.rows_by_id[ref], level, folders.image_index)
        if candidate in folders.current:
            return candidate
    return folders.legacy_keys.get(row["folder_key"])


def _move_favorite(db, row, target, identity, meta_by_key):
    level, ref = identity
    existing = meta_by_key.get(target)
    name = (existing["custom_name"] if existing else None) or row["custom_name"]
    favorite = bool((existing["starred"] if existing else False) or row["starred"])
    db.upsert_folder_meta(target, custom_name=name, favorite=favorite,
                          level=level, ref_prompt_id=ref)
    db.delete_folder_meta(row["folder_key"])
    meta_by_key[target] = {"folder_key": target, "custom_name": name, "starred": favorite,
                           "level": level, "ref_prompt_id": ref}
    meta_by_key.pop(row["folder_key"], None)
