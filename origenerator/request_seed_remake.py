from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from origenerator import gallery
from origenerator.branch_session import is_branch_session
from origenerator.file_numbers import NUMBERED
from origenerator.gallery_edits import GalleryEdits
from origenerator.generation_config import (
    ConfigSnapshot,
    configs_match,
    filled_params,
    find_duplicate_generation,
    merge_denormalized,
    seeds_of,
)
from origenerator.generation_state import GenerationSource, GenerationStatus, source_of
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.regeneration import why_it_cannot_be_made_again
from origenerator.trash import Trash
from origenerator.workflows import workflow_named

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Remake:
    item: dict
    seeds: dict


def is_a_request(request: dict) -> bool:
    return bool(str(request.get("heard") or "").strip() or str(request.get("asked") or "").strip())


def wrong_seed_request_images(rows: list[dict], requests: list[dict]) -> list[Remake]:
    by_id = {row["prompt_id"]: row for row in rows}
    asked_of = {request["prompt_id"]: request["source_prompt_id"]
                for request in requests if is_a_request(request)}
    found = []
    for row in rows:
        if not _a_finished_image(row):
            continue
        chain = _the_chain_up_from(row, by_id, asked_of)
        right = _seeds_of(chain[-1])
        if len(chain) > 1 and right and _seeds_of(row) != right:
            found.append((len(chain), Remake(row, right)))
    return [remake for _depth, remake in sorted(found, key=lambda each: each[0])]


def _a_finished_image(row: dict) -> bool:
    return (row.get("status") == GenerationStatus.COMPLETED
            and source_of(row) == GenerationSource.GENERATED
            and not row.get("enhance_of")
            and gallery.media_type_of_row(row) == MediaType.IMAGE)


def _the_chain_up_from(row: dict, by_id: dict, asked_of: dict) -> list[dict]:
    chain = [row]
    walked = {row["prompt_id"]}
    while (parent := by_id.get(asked_of.get(chain[-1]["prompt_id"]))) is not None:
        if parent.get("workflow_name") != row.get("workflow_name") or parent["prompt_id"] in walked:
            break
        chain.append(parent)
        walked.add(parent["prompt_id"])
    return chain


ALREADY_MADE = "already made"
CANNOT_BE_MADE_AGAIN = "cannot be made again"
REMAKE_FAILED = "remake failed"


@dataclass
class Tally:
    found: int = 0
    queued: int = 0
    remade: int = 0
    waiting: int = 0
    left: dict[str, list[str]] = field(default_factory=dict)

    def leave(self, why: str, prompt_id: str) -> None:
        self.left.setdefault(why, []).append(prompt_id)


class RemakesInTheQueue:
    def __init__(self, db, jobs, *, client, places: OutputPlaces, trash_dir: Path, why_not=None):
        self._db = db
        self._jobs = jobs
        self._client = client
        self._places = places
        self._trash_dir = trash_dir
        self._why_not = why_not or (lambda item: why_it_cannot_be_made_again(item, client.folders))
        jobs.finished.connect(self._landed)

    def start(self) -> Tally:
        if self._client is None:
            return Tally()
        return remake_what_took_the_wrong_seed(self._db, queue=self._queue, places=self._places,
                                               trash=self._trash, why_not=self._why_not)

    def _queue(self, item: dict, workflow, params: dict) -> str | None:
        return self._jobs.start_prepared(f"remake/{item['prompt_id']}", workflow, params,
                                         source=GenerationSource.REMAKE)

    def _landed(self, _key: str, prompt_id: str, _origin: str = "") -> None:
        run = self._db.get_generation(prompt_id)
        if run is not None and source_of(run) == GenerationSource.REMAKE:
            put_in_place(self._db, run, places=self._places, trash=self._trash)

    def _trash(self, rows: list[dict]) -> None:
        GalleryEdits(self._db, self._places, Trash(self._trash_dir)).delete_rows(rows)


def remake_what_took_the_wrong_seed(db, *, queue, places: OutputPlaces, trash, why_not,
                                    environ=os.environ) -> Tally:
    tally = Tally()
    if is_branch_session(environ):
        return tally
    for run in [row for row in db.list_generations() if source_of(row) == GenerationSource.REMAKE]:
        if run.get("status") == GenerationStatus.COMPLETED:
            tally.remade += put_in_place(db, run, places=places, trash=trash)
        elif run.get("status") == GenerationStatus.ERROR:
            db.delete_generation(run["prompt_id"])
            tally.leave(REMAKE_FAILED, run.get("backfill_of") or run["prompt_id"])
    rows = db.list_generations()
    waiting = {row.get("backfill_of") for row in rows if source_of(row) == GenerationSource.REMAKE}
    queued: list[ConfigSnapshot] = []
    for remake in wrong_seed_request_images(rows, db.list_requests()):
        tally.found += 1
        _queue_one(remake, rows, tally, waiting=waiting, queued=queued, queue=queue,
                   why_not=why_not, db=db)
    _log(tally)
    return tally


def _queue_one(remake: Remake, rows: list[dict], tally: Tally, *, waiting, queued, queue,
               why_not, db) -> None:
    prompt_id = remake.item["prompt_id"]
    if prompt_id in waiting:
        tally.waiting += 1
        return
    workflow = workflow_named(remake.item.get("workflow_name") or "")
    if workflow is None or why_not(remake.item):
        tally.leave(CANNOT_BE_MADE_AGAIN, prompt_id)
        return
    params = {**filled_params(remake.item, workflow), **remake.seeds}
    made = ConfigSnapshot(workflow.name, {**workflow.default_params(), **params}, False)
    if (find_duplicate_generation(rows, made) is not None
            or any(configs_match(made, other) for other in queued)):
        tally.leave(ALREADY_MADE, prompt_id)
        return
    queued.append(made)
    run = queue(remake.item, workflow, params)
    if run:
        db.set_backfill_of(run, prompt_id)
        tally.queued += 1


def _log(tally: Tally) -> None:
    if not (tally.found or tally.remade or tally.left):
        return
    logger.info("Request images that took the wrong seed: %d found, %d queued to be made again, "
                "%d already waiting, %d made again in place", tally.found, tally.queued,
                tally.waiting, tally.remade)
    for why, prompt_ids in tally.left.items():
        logger.info("Left %d of them as they are (%s): %s", len(prompt_ids), why,
                    ", ".join(prompt_ids))


def put_in_place(db, run: dict, *, places: OutputPlaces, trash) -> bool:
    item = db.get_generation(run.get("backfill_of") or "")
    if item is None:
        trash([{**run, "source": GenerationSource.GENERATED}])
        return False
    made = gallery.output_disk_files(run, places)
    numbers = _number_of(run), _number_of(item)
    if not made or None in numbers:
        logger.warning("Remake %s of %s has no numbered image on disk to take its place; it "
                       "waits for the next launch", run["prompt_id"], item["prompt_id"])
        return False
    renamed = _renamed(*numbers)
    try:
        if gallery.output_disk_files(item, places):
            _send_the_old_version_to_the_trash(db, item, trash)
        for path in made:
            path.replace(path.with_name(renamed(path.name)))
    except OSError:
        logger.warning("Could not put remake %s under %s's names; it waits for the next launch",
                       run["prompt_id"], item["prompt_id"], exc_info=True)
        return False
    db.remake_in_place(item["prompt_id"], {**run, "output_files": json.dumps(
        [{**entry, "filename": renamed(entry.get("filename") or "")}
         for entry in gallery.row_output_files(run)])})
    db.forget_item_numbers([run["prompt_id"]])
    return True


def _number_of(row: dict) -> str | None:
    for entry in gallery.row_output_files(row):
        if match := NUMBERED.match(entry.get("filename") or ""):
            return f"{match['stem']}_{match['counter']}"
    return None


def _renamed(remade_name: str, old_name: str):
    def renamed(name: str) -> str:
        return old_name + name[len(remade_name):] if name.startswith(remade_name) else name
    return renamed


_NOT_THE_OLD_VERSIONS = dict.fromkeys(
    ("remade_at", "backfill_of", "genau_requested_at", "evolver_exported_at", "evolver_unsent_at",
     "genau_exported_at", "genau_unsent_at", "image_actions", "image_checked", "video_actions",
     "video_checked", "combined_labels", "picture_state", "recipe_category", "recipe_video_id"))


def _send_the_old_version_to_the_trash(db, item: dict, trash) -> None:
    version = {**{column: value for column, value in item.items() if column != "id"},
               **_NOT_THE_OLD_VERSIONS, "starred": 0, "shielded": 0, "fun_time_favorite_owed": 0,
               "prompt_id": str(uuid.uuid4()), "old_version_of": item["prompt_id"]}
    db.insert_rows([version])
    try:
        trash([db.get_generation(version["prompt_id"])])
    except OSError:
        db.delete_generation(version["prompt_id"])
        raise


def _seeds_of(row: dict) -> dict:
    workflow = workflow_named(row.get("workflow_name") or "")
    if workflow is not None:
        return seeds_of(row, workflow)
    seed = merge_denormalized(row).get("seed")
    return {} if seed in (None, "") else {"seed": seed}
