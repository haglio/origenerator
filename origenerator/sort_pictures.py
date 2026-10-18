# ruff: noqa: PLC0415 -- inside the functions, so naming this module costs nothing
"""Open the sorting window on every picture nobody has said what it shows yet,
on its own (:mod:`origenerator.own_window`), beside the app or without it."""
from __future__ import annotations


def _picture_of(row: dict, output_dir):
    """The full-size still where it is on disk, else the stored thumbnail."""
    from origenerator import gallery
    from origenerator.media import MediaType

    found = gallery.resolve_preview(row, output_dir)
    if found is not None and found[1] == MediaType.IMAGE:
        return str(found[0])
    return row.get("thumbnail_path")


def waiting_pictures(db, output_dir) -> list[dict]:
    from origenerator.item_names import ItemNames
    from origenerator.picture_sorting import pictures_to_sort

    names = ItemNames.from_library(db)
    return [{"prompt_id": row["prompt_id"], "name": names.of(row["prompt_id"]),
             "picture_path": _picture_of(row, output_dir)}
            for row in pictures_to_sort(db.list_generations())]


def the_sorting_window():
    """The sorting window on every picture nobody has said an action for, or the
    sentence to say instead when there is none left."""
    from origenerator.config import COMFYUI_OUTPUT_DIR, DB_PATH
    from origenerator.db import Database
    from origenerator.gui.sorting_window import SortingWindow
    from origenerator.picture_marks import mark_for
    from origenerator.picture_states import state_grid
    from origenerator.sorting_session import SortingSession

    db = Database(DB_PATH)
    waiting = waiting_pictures(db, COMFYUI_OUTPUT_DIR)
    if not waiting:
        return "Every picture already says what it shows."

    rows = state_grid()
    marks = {state: str(drawn) for row in rows for state in row
             if (drawn := mark_for(state)) is not None}
    return SortingWindow(SortingSession(waiting, db), rows, marks)


def main() -> int:
    from origenerator.own_window import open_on_its_own

    return open_on_its_own("Sorting pictures", the_sorting_window,
                           launcher="sort_pictures.vbs")


if __name__ == "__main__":
    raise SystemExit(main())
