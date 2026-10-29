from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_support.logging_utils import configure_logging, install_exception_logging
from shared_ui.preview import taskbar_identity

from origenerator import config, fix_training, gallery, lora_training, places_backfill
from origenerator.app_state import AppState
from origenerator.base_backfill import TARGET_KEY as BASE_RENDER_TARGET_KEY
from origenerator.base_backfill import queue_base_renders
from origenerator.branch_session import is_branch_session
from origenerator.enhanced_start_backfill import queue_backfill
from origenerator.experiments.background import queue_experiments
from origenerator.experiments.policy import ExperimentPolicy
from origenerator.generation_state import GenerationSource
from origenerator.landed_while_away import training_notice
from origenerator.media import MediaType
from origenerator.notice_toast import raise_notice
from origenerator.single_instance import Copies
from origenerator.win32 import APP_USER_MODEL_ID
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    did: str
    holds_the_graphics_card: bool


def take_a_turn(*, app_open: Callable[[], bool], training_running: Callable[[], bool],
                comfyui_busy: Callable[[], bool], batches_due: Callable[[], bool],
                queue_batches: Callable[[], None], fix_to_train: Callable[[], object],
                train: Callable[[object], None]) -> Turn:
    if app_open():
        return Turn("nothing: Origenerator is open", training_running())
    if training_running():
        return Turn("nothing: a fix is training", True)
    if comfyui_busy():
        return Turn("nothing: ComfyUI is still working", False)
    if batches_due():
        queue_batches()
        return Turn("handed ComfyUI the work Origenerator left as it closed", training_running())
    if (fix := fix_to_train()) is not None:
        train(fix)
        return Turn(f"started training the {fix.name} fix", True)
    return Turn("nothing to do", training_running())


def _left_work() -> Path:
    return config.LIBRARY_STATE_DIR / "work left for while closed"


def leave_work_for_while_closed() -> None:
    _left_work().touch()


def forget_work_left() -> None:
    _left_work().unlink(missing_ok=True)


def work_left() -> bool:
    return _left_work().exists()


def queue_the_work_left(jobs, rows: list[dict], *, experiments_on: bool, policy) -> int:
    queued = 0
    if experiments_on:
        index = gallery.build_image_config_index(
            [row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE])
        queued += queue_experiments(rows, policy, lambda proposal: jobs.start_prepared(
            gallery.folder_key_for(proposal.workflow.name, proposal.params, index),
            proposal.workflow, proposal.params, source=GenerationSource.EXPERIMENT))
    return queued + queue_base_renders(rows, lambda workflow, params: jobs.start_prepared(
        f"base_render/{params[BASE_RENDER_TARGET_KEY]}", workflow, params,
        source=GenerationSource.BASE_RENDER))


def announce_trainings_that_ended(announce) -> None:
    for job in fix_training.trainings():
        status = lora_training.read_status(job) or {}
        if (job.get("automatic") and status.get("state") in ("done", "failed")
                and not status.get("taken") and not status.get("announced")):
            if (notice := training_notice(job)) is not None:
                announce(notice)
            lora_training.mark_announced(job)


def _comfyui_busy(client) -> bool:
    try:
        return bool(client.fetch_queue())
    except Exception as e:
        logger.info("ComfyUI could not be asked what it is doing: %s", e)
        return False


def queue_the_backfill(jobs, db, rows: list[dict], *, enhance_settings) -> int:
    from origenerator.gui.enhance_controller import launch_enhancements  # noqa: PLC0415

    def launch(video: dict, workflow, params: dict) -> str | None:
        prompt_id = jobs.start_prepared(f"backfill/{video['prompt_id']}", workflow, params,
                                        source=GenerationSource.BACKFILL)
        if prompt_id is not None:
            db.set_backfill_of(prompt_id, video["prompt_id"])
        return prompt_id

    def enhance(images: list[dict]) -> None:
        asks = [(image, params) for image in images
                if (params := gallery.enhance_params_for(image, enhance_settings)) is not None]
        index = gallery.build_image_config_index(
            [row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE])
        launch_enhancements(jobs, db, asks, index, source=GenerationSource.BACKFILL)

    return queue_backfill(rows, launch, enhance=enhance)


def hand_comfyui_the_work_left(db, client, ui: AppState) -> None:
    from PyQt6.QtCore import QCoreApplication  # noqa: PLC0415

    from origenerator.gui.job_queue import JobQueue  # noqa: PLC0415

    _app = QCoreApplication.instance() or QCoreApplication([])
    jobs = JobQueue(db, client)
    queued = queue_the_backfill(
        jobs, db, db.list_generations(),
        enhance_settings=gallery.EnhanceSettings.parse(ui.get("enhance_settings")))
    queued += queue_the_work_left(jobs, db.list_generations(),
                                  experiments_on=ui.get("experiments_enabled") is True,
                                  policy=ExperimentPolicy(registry=WORKFLOW_REGISTRY,
                                                          rng=random.Random()))
    queued += places_backfill.queue_finding_for_the_absence(db, client)
    jobs.flush_to_server()
    forget_work_left()
    logger.info("Handed ComfyUI %d run(s) Origenerator left for while it is closed", queued)


def _train(client, part, ui: AppState) -> None:
    try:
        client.free_memory()
    except Exception as e:
        logger.info("ComfyUI could not be asked to let go of its models: %s", e)
    settings = gallery.EnhanceSettings.parse(ui.get("enhance_settings"))
    fix_training.start(fix_training.training_job(
        part, fix_training.model_to_train_for(settings.params), automatic=True))
    logger.info("Started training the %s fix while Origenerator is closed", part.name)


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

    def app_open() -> bool:
        return copies.one_holds_the_library() or copies.one_is_closing()

    if not app_open():
        identity = taskbar_identity(APP_USER_MODEL_ID, None)
        announce_trainings_that_ended(lambda notice: raise_notice(identity, notice))
    turn = take_a_turn(
        app_open=app_open,
        training_running=lambda: bool(fix_training.running_trainings()),
        comfyui_busy=lambda: _comfyui_busy(client), batches_due=work_left,
        queue_batches=lambda: hand_comfyui_the_work_left(db, client, ui),
        fix_to_train=fix_training.fix_to_train, train=lambda part: _train(client, part, ui))
    print(json.dumps({"did": turn.did, "holds_the_graphics_card": turn.holds_the_graphics_card}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
