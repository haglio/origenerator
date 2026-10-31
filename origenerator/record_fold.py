from __future__ import annotations

from origenerator.gallery_contract import LANES


def file_key(entry: dict) -> tuple[str, str]:
    return entry.get("subfolder") or "", entry.get("filename") or ""


def fold_record_into(db, rows, folded: dict, keeper: dict) -> None:
    _carry_over_what_the_user_put_on_it(db, folded, keeper)
    _repoint_at_the_record_that_stays(db, rows, folded, keeper)


def lanes_owed(folded: dict, keeper: dict) -> list[str]:
    return [lane for lane, stamps in LANES.items()
            if folded.get(stamps["sent"])
            and not keeper.get(stamps["sent"]) and not keeper.get(stamps["unsent"])]


def _carry_over_what_the_user_put_on_it(db, folded: dict, keeper: dict) -> None:
    if folded.get("starred") and not keeper.get("starred"):
        db.set_generation_favorite(keeper["prompt_id"], True)
    inherited = {column: folded[column]
                 for column in ("enhance_history", "original_files", "thumbnail_path")
                 if folded.get(column) and not keeper.get(column)}
    if inherited:
        db.update_generation(keeper["prompt_id"], **inherited)


def _repoint_at_the_record_that_stays(db, rows, folded: dict, keeper: dict) -> None:
    gone, stays = folded["prompt_id"], keeper["prompt_id"]
    for row in rows:
        if row.get("enhance_of") == gone:
            db.set_enhance_target(row["prompt_id"], stays)
        if row.get("source_video") == gone:
            db.set_settings_source(row["prompt_id"], category=row.get("act"),
                                   video_prompt_id=stays)
    db.repoint_combine_video_uses(gone, stays)
    for folder_meta in db.folder_meta_full():
        if folder_meta.get("ref_prompt_id") == gone:
            db.upsert_folder_meta(folder_meta["folder_key"],
                                  custom_name=folder_meta.get("custom_name"),
                                  favorite=bool(folder_meta.get("starred")),
                                  level=folder_meta.get("level"), ref_prompt_id=stays)
    db.repoint_item_in_custom_folders(gone, stays)
    for held in db.folders_in_custom_folders():
        if held.get("ref_prompt_id") == gone:
            db.stamp_folder_in_custom_folder(held["folder_id"], held["folder_key"],
                                             level=held.get("level"), ref_prompt_id=stays)
