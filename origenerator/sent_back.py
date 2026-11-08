from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NamedTuple

from app_support import wrong_actions

from origenerator.config import EVOLVER_SOURCE, LIBRARY_STATE_DIR
from origenerator.evolver_upscales import original_stem
from origenerator.gallery import media_type_of_row
from origenerator.gallery.output import output_file_path, row_output_files
from origenerator.gallery.source_image import image_actions_row, start_images_among
from origenerator.item_actions import ItemActions, actions_of, combined_actions
from origenerator.media import MediaType
from origenerator.published_actions import set_actions

logger = logging.getLogger(__name__)

FILE_NAME = "sent_back_for_actions.json"


class SentBack:
    def __init__(self, path):
        self._path = Path(path)

    def ids(self) -> tuple[str, ...]:
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ()
        return tuple(item for item in held if isinstance(item, str)) if isinstance(held, list) else ()

    def add(self, prompt_ids) -> None:
        self._write(dict.fromkeys((*self.ids(), *prompt_ids)))

    def keep_only(self, prompt_ids) -> None:
        held = self.ids()
        kept = [prompt_id for prompt_id in held if prompt_id in prompt_ids]
        if len(kept) != len(held):
            self._write(kept)

    def _write(self, prompt_ids) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(list(prompt_ids), indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
        except OSError as refused:
            logger.warning("Could not keep the items sent back for their actions: %s", refused)


def the_librarys() -> SentBack:
    return SentBack(LIBRARY_STATE_DIR / FILE_NAME)


def _images_among(rows: list[dict]):
    return start_images_among([row for row in rows if media_type_of_row(row) == MediaType.IMAGE])


def _send_back(db, video: dict, start_image_of, kept: SentBack) -> str:
    holder = image_actions_row(video, start_image_of(video))
    asked = {(holder["prompt_id"], MediaType.IMAGE): actions_of(holder, MediaType.IMAGE),
             (video["prompt_id"], MediaType.VIDEO): actions_of(video, MediaType.VIDEO)}
    said = ", ".join(combined_actions(*asked.values()))
    if not said:
        return ""
    for (prompt_id, side), item_actions in asked.items():
        if item_actions.actions:
            set_actions(db, prompt_id, side, ItemActions())
    kept.add(dict.fromkeys(prompt_id for prompt_id, _side in reversed(asked)))
    return said


def send_back(db, prompt_id: str, kept: SentBack) -> str:
    rows = db.list_generations()
    video = next((row for row in rows if row["prompt_id"] == prompt_id), None)
    if video is None:
        return ""
    return _send_back(db, video, _images_among(rows), kept)


def _same_place(one, other) -> bool:
    return Path(one).as_posix().casefold() == Path(other).as_posix().casefold()


def _made_here(said: Path, video: dict, places) -> bool:
    stem = original_stem(said)
    if stem is None or said.parent.name != EVOLVER_SOURCE:
        return False
    return any(output_file_path(file, places).stem == stem for file in row_output_files(video))


def _played_as(said: Path, video: dict, places) -> bool:
    return (any(_same_place(output_file_path(file, places), said)
                for file in row_output_files(video))
            or _made_here(said, video, places))


def take_in(db, places, state_dir, kept: SentBack) -> int:
    said = wrong_actions.take(state_dir)
    if not said:
        return 0
    rows = db.list_generations()
    videos = [row for row in rows if media_type_of_row(row) == MediaType.VIDEO]
    start_image_of = _images_among(rows)
    taken = 0
    for played in map(Path, said):
        found = [video for video in videos if _played_as(played, video, places)]
        if len(found) != 1:
            logger.info("No one item of this app's is the video said to have the wrong actions "
                        "(%d found)", len(found))
            continue
        if _send_back(db, found[0], start_image_of, kept):
            taken += 1
    return taken


def _waits_on_a_side(row: dict) -> bool:
    return not all(actions_of(row, side).actions for side in (MediaType.IMAGE, MediaType.VIDEO))


class Returned(NamedTuple):
    sent_back: SentBack
    said_in: Path

    def take_in(self, db, places) -> int:
        return take_in(db, places, self.said_in, self.sent_back)

    def still_waiting(self, rows: list[dict]) -> tuple[str, ...]:
        self.sent_back.keep_only({row["prompt_id"] for row in rows if _waits_on_a_side(row)})
        return self.sent_back.ids()


def to_the_library() -> Returned:
    return Returned(the_librarys(), LIBRARY_STATE_DIR)
