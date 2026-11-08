# ruff: noqa: PLC0415 -- inside the functions, so naming this module costs nothing
from __future__ import annotations

from origenerator.media import MediaType

TITLE = "Action setter tool"
LOCKS_FILE = "action_setter_locks.json"
NOTHING_WAITING = {MediaType.IMAGE: "Every image already has its actions.",
                   MediaType.VIDEO: "Every video already has its actions."}


def _shown_from(row: dict, places, side: str):
    from origenerator import gallery

    found = gallery.resolve_preview(row, places)
    if found is not None and found[1] == side:
        return str(found[0])
    return row.get("thumbnail_path") if side == MediaType.IMAGE else None


def _labels_now(row: dict, side: str):
    from origenerator.action_labels import is_labeled, labels_of

    return labels_of(row, side) if is_labeled(row, side) else None


def _opened_on(first: str, rows: list[dict], line: list):
    from origenerator.action_setter import Waiting

    if not first:
        return None
    found = next((entry for entry in line if entry.holder["prompt_id"] == first), None)
    if found is not None:
        return found
    row = next((row for row in rows if row["prompt_id"] == first), None)
    return Waiting(row, row) if row is not None else None


def waiting_items(db, places, side: str, first: str = "") -> list[dict]:
    from origenerator.action_setter import waiting
    from origenerator.item_names import ItemNames

    rows = db.list_generations()
    line = waiting(rows, side)
    opened_on = _opened_on(first, rows, line)
    if opened_on is not None:
        line = [opened_on, *(entry for entry in line if entry.holder["prompt_id"] != first)]
    names = ItemNames.from_library(db)
    return [{"prompt_id": entry.holder["prompt_id"], "name": names.of(entry.shown["prompt_id"]),
             "path": _shown_from(entry.holder, places, side),
             "labels": _labels_now(entry.holder, side)}
            for entry in line]


class AnswersTold:
    def __init__(self, db, heard):
        self._db, self._heard = db, heard

    def set_labels(self, prompt_id: str, side: str, labels) -> None:
        from origenerator.published_labels import set_labels

        set_labels(self._db, prompt_id, side, labels)
        self._heard(prompt_id, side, labels)


def _nobody_listening(_prompt_id: str, _side: str, _labels) -> None:
    pass


def asks_to_keep_going(first: str):
    from origenerator.gui.action_setter_window import ask_to_keep_going

    return ask_to_keep_going if first else None


def the_setter_tool(side: str = MediaType.IMAGE, first: str = "", heard=_nobody_listening):
    from origenerator.action_drawings import drawing_for
    from origenerator.action_setter import Locks, SetterSession
    from origenerator.action_vocabulary import vocabulary
    from origenerator.config import DB_PATH, OUTPUT_PLACES, STATE_DIR
    from origenerator.db import Database
    from origenerator.gui.action_setter_window import ActionSetterWindow

    db = Database(DB_PATH)
    waiting = waiting_items(db, OUTPUT_PLACES, side, first)
    if not waiting:
        return NOTHING_WAITING[side]
    named = vocabulary(side)
    drawings = {name: str(drawn) for name in named.buttons
                if (drawn := drawing_for(named.drawing_name(name))) is not None}
    return ActionSetterWindow(SetterSession(waiting, AnswersTold(db, heard), side),
                              named, drawings, Locks(STATE_DIR / LOCKS_FILE),
                              keep_going=asks_to_keep_going(first))


def main() -> int:
    from origenerator.own_window import open_on_its_own

    return open_on_its_own(TITLE, the_setter_tool, launcher="sort_images.vbs")


if __name__ == "__main__":
    raise SystemExit(main())
