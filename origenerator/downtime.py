from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_support.logging_utils import configure_logging, install_exception_logging

from origenerator import collection_notes, config, flick_finales, gallery, places_backfill
from origenerator.app_state import AppState
from origenerator.base_backfill import TARGET_KEY as BASE_RENDER_TARGET_KEY
from origenerator.base_backfill import queue_base_renders
from origenerator.branch_session import is_branch_session
from origenerator.experiments.background import queue_experiments
from origenerator.experiments.policy import ExperimentPolicy
from origenerator.generation_state import GenerationSource
from origenerator.landed_while_away import running_trainings
from origenerator.single_instance import Copies
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    did: str
    holds_the_graphics_card: bool


@dataclass(frozen=True)
class Machine:
    app_open: Callable[[], bool]
    training_running: Callable[[], bool]
    comfyui_busy: Callable[[], bool]
    batches_due: Callable[[], bool]
    queue_batches: Callable[[], None]
    notes_due: Callable[[], bool]
    take_notes: Callable[[], None]


def _nothing_while_it_is_in_use(machine: Machine) -> Turn | None:
    if machine.app_open():
        return Turn("nothing: Origenerator is open", machine.training_running())
    if machine.training_running():
        return Turn("nothing: a fix is training", True)
    if machine.comfyui_busy():
        return Turn("nothing: ComfyUI is still working", False)
    return None


def take_a_turn(machine: Machine) -> Turn:
    if (nothing := _nothing_while_it_is_in_use(machine)) is not None:
        return nothing
    if machine.batches_due():
        machine.queue_batches()
        return Turn("handed ComfyUI the work Origenerator left as it closed", machine.training_running())
    if machine.notes_due():
        machine.take_notes()
        return Turn("took notes on the collection", machine.training_running())
    return Turn("nothing to do", machine.training_running())


def _left_work() -> Path:
    return config.LIBRARY_STATE_DIR / "work left for while closed"


def leave_work_for_while_closed() -> None:
    _left_work().touch()


def forget_work_left() -> None:
    _left_work().unlink(missing_ok=True)


def work_left() -> bool:
    return _left_work().exists()


def queue_the_work_left(jobs, db, rows: list[dict], *, experiments_on: bool, finales_on: bool,
                        policy) -> int:
    queued = flick_finales.queue_finales(jobs, db, rows) if finales_on else 0
    if experiments_on:
        index = gallery.image_config_index_of(rows)
        queued += queue_experiments(rows, policy, lambda proposal: jobs.start_prepared(
            gallery.folder_key_for(proposal.workflow.name, proposal.params, index),
            proposal.workflow, proposal.params, source=GenerationSource.EXPERIMENT))
    return queued + queue_base_renders(rows, lambda workflow, params: jobs.start_prepared(
        f"base_render/{params[BASE_RENDER_TARGET_KEY]}", workflow, params,
        source=GenerationSource.BASE_RENDER))


def _comfyui_busy(client) -> bool:
    try:
        return bool(client.fetch_queue())
    except Exception as e:
        logger.info("ComfyUI could not be asked what it is doing: %s", e)
        return False


def _handed_over(db, client, queue: Callable[[object], int]) -> int:
    from PySide6.QtCore import QCoreApplication  # noqa: PLC0415

    from origenerator.gui.job_queue import JobQueue  # noqa: PLC0415

    _app = QCoreApplication.instance() or QCoreApplication([])
    jobs = JobQueue(db, client)
    jobs.close()
    queued = queue(jobs)
    jobs.flush_to_server()
    return queued


def hand_comfyui_the_work_left(db, client, ui: AppState) -> None:
    def everything(jobs) -> int:
        return (queue_the_work_left(jobs, db, db.list_generations(),
                                      experiments_on=ui.get("experiments_enabled") is True,
                                      finales_on=flick_finales.SWITCHED_ON,
                                      policy=ExperimentPolicy(registry=WORKFLOW_REGISTRY,
                                                              rng=random.Random()))
                + places_backfill.queue_finding_for_the_absence(db, client))

    queued = _handed_over(db, client, everything)
    forget_work_left()
    logger.info("Handed ComfyUI %d run(s) Origenerator left for while it is closed", queued)


def main() -> int:
    if is_branch_session():
        print(json.dumps({"did": "nothing: a preview leaves this to production",
                          "holds_the_graphics_card": False}))
        return 0
    configure_logging("", config.STATE_DIR / "origenerator.log")
    install_exception_logging(logger)
    from origenerator.comfyui_client import ComfyUIClient  # noqa: PLC0415
    from origenerator.db import Database  # noqa: PLC0415

    db = Database(config.LIBRARY_STATE_DIR / "origenerator.db")
    client = ComfyUIClient(folders=config.COMFYUI_FOLDERS)
    copies = Copies(config.LIBRARY_STATE_DIR)
    ui = AppState(config.UI_STATE_PATH)

    turn = take_a_turn(Machine(
        app_open=lambda: copies.one_holds_the_library() or copies.one_is_closing(),
        training_running=lambda: bool(running_trainings()),
        comfyui_busy=lambda: _comfyui_busy(client), batches_due=work_left,
        queue_batches=lambda: hand_comfyui_the_work_left(db, client, ui),
        notes_due=lambda: collection_notes.are_due(db, config.COLLECTION_NOTES_PATH),
        take_notes=lambda: collection_notes.take_a_sitting(db, client, config.COLLECTION_NOTES_PATH)))
    print(json.dumps({"did": turn.did, "holds_the_graphics_card": turn.holds_the_graphics_card}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
