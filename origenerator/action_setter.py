from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import NamedTuple

from origenerator import gallery
from origenerator.action_labels import Labels, labels_of
from origenerator.gallery.source_image import (
    image_labels_row,
    inherits_image_labels,
    start_images_among,
)
from origenerator.generation_state import GenerationStatus, in_sight
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


def _its_own_image_labels(rows: list[dict]) -> list[Waiting]:
    start_image_of = start_images_among(
        [row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE])
    return [Waiting(image_labels_row(video, start), video) for video in rows
            if _finished(video, MediaType.VIDEO)
            and not inherits_image_labels(video, start := start_image_of(video))]


def waiting(rows: list[dict], side: str) -> list[Waiting]:
    found = [Waiting(row, row) for row in rows if _finished(row, side)]
    if side == MediaType.IMAGE:
        found += _its_own_image_labels(rows)
    return sorted((entry for entry in found if not labels_of(entry.holder, side).actions),
                  reverse=True, key=lambda entry: (bool(entry.shown.get("starred")),
                                                   entry.shown.get("created_at") or ""))


class SetterSession:
    def __init__(self, items: list[dict], store, side: str):
        self._line = deque(items)
        self._store = store
        self._side = side
        self._set: list[tuple[dict, str, Labels, bool]] = []

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
    def last(self) -> tuple[str, Labels] | None:
        return self._set[-1][1:3] if self._set else None

    @property
    def can_undo(self) -> bool:
        return bool(self._set)

    def set_as(self, said: str, labels: Labels) -> None:
        if not self._line:
            return
        item = self._line.popleft()
        self._store.set_labels(item["prompt_id"], self._side, labels)
        self._set.append((item, said, labels))

    def skip(self) -> None:
        self._line.rotate(-1)

    def undo(self) -> None:
        if not self._set:
            return
        item, _said, _labels = self._set.pop()
        self._store.set_labels(item["prompt_id"], self._side, item.get("labels"))
        self._line.appendleft(item)


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
