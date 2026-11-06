# ruff: noqa: PLC0415 -- inside the functions, so naming this module costs nothing
from __future__ import annotations


def _image_of(row: dict, places):
    from origenerator import gallery
    from origenerator.media import MediaType

    found = gallery.resolve_preview(row, places)
    if found is not None and found[1] == MediaType.IMAGE:
        return str(found[0])
    return row.get("thumbnail_path")


def waiting_images(db, places, first: str = "") -> list[dict]:
    from origenerator.image_sorting import images_to_sort
    from origenerator.item_names import ItemNames

    rows = db.list_generations()
    line = [row for row in images_to_sort(rows) if row["prompt_id"] != first]
    opened_on = next((row for row in rows if row["prompt_id"] == first), None) if first else None
    if opened_on is not None:
        line.insert(0, opened_on)
    names = ItemNames.from_library(db)
    return [{"prompt_id": row["prompt_id"], "name": names.of(row["prompt_id"]),
             "image_path": _image_of(row, places)}
            for row in line]


class AnswersTold:
    def __init__(self, db, heard):
        self._db, self._heard = db, heard

    def set_image_state(self, prompt_id: str, state: str | None) -> None:
        self._db.set_image_state(prompt_id, state)
        self._heard(prompt_id, state or "")


def _nobody_listening(_prompt_id: str, _said: str) -> None:
    pass


def the_sorting_window(first: str = "", heard=_nobody_listening):
    from origenerator.action_drawings import drawing_for
    from origenerator.config import DB_PATH, OUTPUT_PLACES
    from origenerator.db import Database
    from origenerator.gui.sorting_window import SortingWindow
    from origenerator.image_states import state_grid
    from origenerator.sorting_session import SortingSession

    db = Database(DB_PATH)
    waiting = waiting_images(db, OUTPUT_PLACES, first)
    if not waiting:
        return "Every image already says what it shows."

    tiles = state_grid()
    drawings = {tile.state: str(drawn) for tile in tiles
                if (drawn := drawing_for(tile.state)) is not None}
    return SortingWindow(SortingSession(waiting, AnswersTold(db, heard)), tiles, drawings)


def main() -> int:
    from origenerator.own_window import open_on_its_own

    return open_on_its_own("Sorting images", the_sorting_window,
                           launcher="sort_images.vbs")


if __name__ == "__main__":
    raise SystemExit(main())
