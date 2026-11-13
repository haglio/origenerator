from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import NamedTuple

from origenerator import gallery
from origenerator.gallery.source_image import (
    image_actions_row,
    inherits_image_actions,
    start_images_among,
)
from origenerator.generation_state import GenerationStatus, in_sight
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType

logger = logging.getLogger(__name__)


class Waiting(NamedTuple):
    holder: dict
    shown: dict


def _finished(row: dict, kind: str) -> bool:
    return (row.get("status") == GenerationStatus.COMPLETED
            and in_sight(row)
            and gallery.produced_output(row)
            and gallery.media_type_of_row(row) == kind
            and not gallery.is_enhance_product_row(row))


def _its_own_image_actions(rows: list[dict]) -> list[Waiting]:
    start_image_of = start_images_among(
        [row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE])
    return [Waiting(image_actions_row(video, start), video) for video in rows
            if _finished(video, MediaType.VIDEO)
            and not inherits_image_actions(video, start := start_image_of(video))]


def holders(rows: list[dict], side: str) -> list[Waiting]:
    found = [Waiting(row, row) for row in rows if _finished(row, side)]
    if side == MediaType.IMAGE:
        found += _its_own_image_actions(rows)
    return sorted(found, reverse=True, key=lambda entry: (bool(entry.shown.get("starred")),
                                                         entry.shown.get("created_at") or ""))


def waiting(rows: list[dict], side: str, *, sent_back: tuple[str, ...] = ()) -> list[Waiting]:
    without_actions = [entry for entry in holders(rows, side)
                       if not actions_of(entry.holder, side).actions]
    order = {prompt_id: place for place, prompt_id in enumerate(sent_back)}
    return sorted(without_actions, key=lambda entry: order.get(entry.holder["prompt_id"], len(order)))


def in_folders(line: list[Waiting], every: list[Waiting], folder_of) -> list[list[Waiting]]:
    folders: dict[str, list[Waiting]] = {}
    for entry in line:
        folders.setdefault(folder_of(entry.shown["prompt_id"]), [])
    for entry in every:
        held = folders.get(folder_of(entry.shown["prompt_id"]))
        if held is not None:
            held.append(entry)
    return list(folders.values())


class Answer(NamedTuple):
    folder: dict
    said: str
    item_actions: ItemActions
    replaced: dict


class Thrown(NamedTuple):
    folder: dict


def _shown_id(item: dict) -> str:
    return item.get("shown_id") or item["prompt_id"]


class SetterSession:
    def __init__(self, folders: list[dict], store, side: str, rubbish=None):
        self._line = deque(folders)
        self._store = store
        self._side = side
        self._rubbish = rubbish
        self._done: list[Answer | Thrown] = []

    @property
    def side(self) -> str:
        return self._side

    @property
    def current(self) -> dict | None:
        return self._line[0] if self._line else None

    @property
    def remaining(self) -> int:
        return len(self._line)

    @property
    def last(self) -> tuple[str, ItemActions] | None:
        answered = next((done for done in reversed(self._done) if isinstance(done, Answer)), None)
        return (answered.said, answered.item_actions) if answered is not None else None

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    def set_as(self, said: str, item_actions: ItemActions) -> None:
        if not self._line:
            return
        folder = self._line.popleft()
        replaced = {}
        for item in folder["items"]:
            replaced.update(self._store.set_actions(item["prompt_id"], self._side, item_actions))
        self._done.append(Answer(folder, said, item_actions, replaced))

    def skip(self) -> None:
        self._line.rotate(-1)

    def trash(self) -> None:
        if not self._line or self._rubbish is None:
            return
        folder = self._line.popleft()
        for item in folder["items"]:
            self._rubbish.away(_shown_id(item))
        self._done.append(Thrown(folder))

    def undo(self) -> None:
        if not self._done:
            return
        done = self._done.pop()
        if isinstance(done, Thrown):
            for item in done.folder["items"]:
                self._rubbish.back(_shown_id(item))
        else:
            self._store.put_back(self._side, done.replaced)
        self._line.appendleft(done.folder)


class Locks:
    def __init__(self, path: Path):
        self._path = path

    def _read(self) -> dict:
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return held if isinstance(held, dict) else {}

    def held(self, side: str) -> dict[str, bool]:
        boxes = self._read().get(side)
        return {name: checked for name, checked in boxes.items()
                if isinstance(checked, bool)} if isinstance(boxes, dict) else {}

    def hold(self, side: str, name: str, checked: bool) -> None:
        self._write(side, {**self.held(side), name: checked})

    def let_go(self, side: str, name: str) -> None:
        self._write(side, {held: checked for held, checked in self.held(side).items()
                           if held != name})

    def _write(self, side: str, boxes: dict[str, bool]) -> None:
        held = {**self._read(), side: boxes}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(held, indent=2) + "\n", encoding="utf-8", newline="\n")
        except OSError as refused:
            logger.warning("Could not keep the action setter tool's locks: %s", refused)
