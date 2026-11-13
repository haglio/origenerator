# ruff: noqa: PLC0415 -- inside the functions, so naming this module costs nothing
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator.media import MediaType

TITLE = "Action setter tool"
LOCKS_FILE = "action_setter_locks.json"
NOTHING_WAITING = {MediaType.IMAGE: "Every image already has its actions.",
                   MediaType.VIDEO: "Every video already has its actions."}


def _opened_on(first: str, rows: list[dict], every: list) -> list:
    from origenerator.action_setter import Waiting

    if not first:
        return []
    found = next((entry for entry in every if entry.holder["prompt_id"] == first), None)
    if found is not None:
        return [found]
    row = next((row for row in rows if row["prompt_id"] == first), None)
    return [Waiting(row, row)] if row is not None else []


def _leaf_folders(rows: list[dict]):
    from origenerator import gallery

    def walk(groups):
        for group in groups:
            if isinstance(group, gallery.SettingsGroup):
                yield group
            yield from walk(gallery.child_groups(group))

    return {row["prompt_id"]: group for group in walk(gallery.build_gallery_tree(rows, {}))
            for row in gallery.rows_under(group)}


def _shared(item_actions: list):
    return item_actions[0] if item_actions and len(set(item_actions)) == 1 else None


def waiting_folders(db, places, side: str, first: str = "", *, returned=None) -> list[dict]:
    from origenerator.action_setter import holders, in_folders, waiting
    from origenerator.item_names import ItemNames
    from origenerator.sent_back import to_the_library

    returned = returned or to_the_library()
    returned.take_in(db, places)
    rows = db.list_generations()
    every = holders(rows, side)
    line = waiting(rows, side, sent_back=returned.still_waiting(rows))
    leaves = _leaf_folders(rows)
    names = ItemNames.from_library(db)

    def folder_of(prompt_id: str) -> str:
        leaf = leaves.get(prompt_id)
        return leaf.key if leaf is not None else prompt_id

    opened_on = _opened_on(first, rows, every)
    every += [entry for entry in opened_on if entry not in every]
    return [_shown_as_a_folder(entries, side, leaves.get(entries[0].shown["prompt_id"]), names)
            for entries in in_folders([*opened_on, *line], every, folder_of)]


def _shown_as_a_folder(entries: list, side: str, leaf, names) -> dict:
    from origenerator.item_actions import actions_if_any

    shown = entries[0].shown["prompt_id"]
    items = [{"prompt_id": entry.holder["prompt_id"], "shown_id": entry.shown["prompt_id"],
              "actions": actions_if_any(entry.holder, side)} for entry in entries]
    return {"key": leaf.key if leaf is not None else shown,
            "name": leaf.label if leaf is not None else names.of(shown),
            "items": items,
            "thumbnails": [entry.shown.get("thumbnail_path") for entry in entries],
            "actions": _shared([item["actions"] for item in items
                                if item["actions"] is not None])}


class AnswersTold:
    def __init__(self, db, heard):
        self._db, self._heard = db, heard

    def set_actions(self, prompt_id: str, side: str, item_actions) -> dict:
        from origenerator.published_actions import set_actions

        replaced = set_actions(self._db, prompt_id, side, item_actions)
        for each in replaced:
            self._heard(each, side, item_actions)
        return replaced

    def put_back(self, side: str, replaced: dict) -> None:
        from origenerator.published_actions import put_back

        put_back(self._db, side, replaced)
        for prompt_id, item_actions in replaced.items():
            self._heard(prompt_id, side, item_actions)


def _nobody_listening(_prompt_id: str, _side: str, _item_actions) -> None:
    pass


def asks_to_keep_going(first: str):
    from origenerator.gui.action_setter_window import ask_to_keep_going

    return ask_to_keep_going if first else None


class ThrownInto(NamedTuple):
    db: object
    delete_rows: Callable[[list[dict]], object]
    restore: Callable[[list[str]], object]

    def away(self, prompt_id: str) -> None:
        row = self.db.get_generation(prompt_id)
        if row is not None:
            self.delete_rows([row])

    def back(self, prompt_id: str) -> None:
        self.restore([prompt_id])


class SetterHost(NamedTuple):
    rubbish: Callable[[object], ThrownInto]
    listen: Callable[[object], None]


def the_setter_tool(side: str = MediaType.IMAGE, first: str = "", heard=_nobody_listening, *,
                    host: SetterHost | None = None):
    from origenerator.action_drawings import drawing_for
    from origenerator.action_setter import Locks, SetterSession
    from origenerator.action_vocabulary import vocabulary
    from origenerator.config import DB_PATH, OUTPUT_PLACES, STATE_DIR
    from origenerator.db import Database
    from origenerator.gui.action_setter_window import ActionSetterWindow

    db = Database(DB_PATH)
    waiting = waiting_folders(db, OUTPUT_PLACES, side, first)
    if not waiting:
        return NOTHING_WAITING[side]
    named = vocabulary(side)
    drawings = {name: str(drawn) for name in named.buttons
                if (drawn := drawing_for(named.drawing_name(name))) is not None}
    window = ActionSetterWindow(
        SetterSession(waiting, AnswersTold(db, heard), side,
                      host.rubbish(db) if host is not None else None),
        named, drawings, Locks(STATE_DIR / LOCKS_FILE),
        keep_going=asks_to_keep_going(first))
    if host is not None:
        host.listen(window)
    return window


def _its_own_trash(db) -> ThrownInto:
    from origenerator.config import OUTPUT_PLACES, TRASH_DIR
    from origenerator.gallery_edits import GalleryEdits
    from origenerator.trash import Trash

    edits = GalleryEdits(db, OUTPUT_PLACES, Trash(TRASH_DIR))
    return ThrownInto(db, edits.delete_rows, edits.restore_deleted)


def _listening_while_open(window) -> None:
    from origenerator.voice.hearing import Hearing

    hearing = Hearing(window.words, parent=window)
    hearing.said.connect(lambda said, _spoken_at: window.hear(said))
    window.closed.connect(hearing.close)
    hearing.start()


ON_ITS_OWN = SetterHost(_its_own_trash, _listening_while_open)


def main() -> int:
    from origenerator.own_window import open_on_its_own

    return open_on_its_own(TITLE, lambda: the_setter_tool(host=ON_ITS_OWN),
                           launcher="sort_images.vbs")


if __name__ == "__main__":
    raise SystemExit(main())
