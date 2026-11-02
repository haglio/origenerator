from __future__ import annotations

import json
import logging
import math
import threading
import time
from itertools import pairwise
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSignal

from origenerator import comfyui_api, comfyui_launcher, gallery, queue_line
from origenerator.completion import mark_generation_completed
from origenerator.config import COMFYUI_DIR, COMFYUI_HOST, COMFYUI_PORT
from origenerator.generation_config import filled_params, prepared_params
from origenerator.generation_state import GenerationSource, GenerationStatus, source_of
from origenerator.gui.generation_job import (
    GenerationJob,
    JobState,
    insert_generation_row,
    record_unfinished_run,
)
from origenerator.gui.off_thread import run_off_thread
from origenerator.media import MediaType
from origenerator.run_toast import RunOutcome
from origenerator.seed_history import SeedUseKind
from origenerator.timing import elapsed_since
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_PROGRESS_PERSIST_INTERVAL_S = 1.0

COMFYUI_DID_NOT_START = "Origenerator couldn't start ComfyUI."


def bring_up_the_comfyui_here() -> bool:
    return comfyui_launcher.bring_up(logger, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_DIR)


BRING_UP_COMFYUI = bring_up_the_comfyui_here


def _outcome_of(db, job, *, ok: bool, seconds: float | None = None) -> RunOutcome:
    return RunOutcome(
        kind=gallery.job_kind_label(job.workflow.name),
        display_name=job.workflow.display_name,
        seconds=elapsed_since(job.started_at) if seconds is None else seconds,
        ok=ok,
        source=job.source,
        generation=_the_item_it_is_about(db, job),
    )


def _the_item_it_is_about(db, job) -> str:
    row = db.get_generation(job.prompt_id) or {}
    return row.get("enhance_of") or job.prompt_id


def _off_the_gui_thread(run) -> None:
    """ComfyUI can take a minute to accept a prompt; waiting on the GUI thread freezes the window, so the wait runs on a thread while this one pumps events."""
    app = QCoreApplication.instance()
    if app is None:
        run()
        return
    outcome: list = []

    def target():
        try:
            run()
            outcome.append(None)
        except BaseException as e:
            outcome.append(e)

    worker = threading.Thread(target=target, name="comfyui-submit", daemon=True)
    worker.start()
    while worker.is_alive():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        worker.join(0.02)
    if outcome and outcome[0] is not None:
        raise outcome[0]


def _the_users_own(source: str) -> bool:
    return source == GenerationSource.GENERATED


def _named(line: list, prompt_id: str | None):
    return next((job for job in line if job.prompt_id == prompt_id), None)


def _parse_progress_state(raw):
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return state if isinstance(state, dict) else None


class JobQueue(QObject):
    changed = pyqtSignal()
    preview = pyqtSignal(str, str, bytes)
    finished = pyqtSignal(str, str, str)
    failed = pyqtSignal(str, str)
    run_ended = pyqtSignal(object)
    reordered = pyqtSignal()

    def __init__(self, db, client, parent=None, *, clock=time.monotonic, bring_up_comfyui=None):
        super().__init__(parent)
        self._db = db
        self._client = client
        self._clock = clock
        self._bring_up_comfyui = bring_up_comfyui or BRING_UP_COMFYUI
        self._awaiting_comfyui = False
        self._image_asked_at: float | None = None
        self._videos_wait = QTimer(self)
        self._videos_wait.setSingleShot(True)
        self._videos_wait.timeout.connect(self._pump)
        self._jobs: dict[str, list[GenerationJob]] = {}
        self._progress_persist_at: dict[str, float] = {}
        self._on_server: list[GenerationJob] = []
        self._waiting: list[GenerationJob] = []
        self._in_flight: GenerationJob | None = None
        self._takes_over_on_landing: GenerationJob | None = None
        self._first: frozenset[str] = frozenset()
        self._training = None
        self._enhance = None
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def watch_training(self, training) -> None:
        self._training = training
        training.ended.connect(self._let_go_of_training)

    def _let_go_of_training(self, outcome) -> None:
        self._training = None
        self._pump()
        if outcome is not None:
            self.run_ended.emit(outcome)

    @property
    def training(self):
        return self._training

    def _training_holds_the_line(self) -> bool:
        return self._training is not None and self._training.holds_the_line

    def training_holds_the_machine(self) -> bool:
        return self._training_holds_the_line() and self._training.running

    def making_something(self) -> bool:
        return bool(self._on_server) or self._in_flight is not None

    def free_comfyui_memory(self) -> None:
        self._client.free_memory()

    @property
    def jobs(self) -> dict:
        return {key: self._leading(jobs) for key, jobs in self._jobs.items() if jobs}

    @property
    def all_jobs(self) -> list:
        return [job for jobs in self._jobs.values() for job in jobs]

    @property
    def jobs_by_folder(self) -> dict:
        return {key: list(jobs) for key, jobs in self._jobs.items()}

    def job_for(self, key: str):
        jobs = self._jobs.get(key)
        return self._leading(jobs) if jobs else None

    def _leading(self, jobs: list) -> GenerationJob:
        place = {pid: index for index, pid in enumerate(self.queue_order)}
        return min(jobs, key=lambda job: (-1 if job is self._in_flight
                                          else place.get(job.prompt_id, len(place))))

    def newest_job_for(self, key: str):
        jobs = self._jobs.get(key)
        return jobs[-1] if jobs else None

    def job_for_prompt(self, prompt_id: str | None):
        return next((j for j in self.all_jobs if j.prompt_id == prompt_id), None)

    def job_for_origin(self, origin: str | None):
        if origin is None:
            return None
        return next((j for j in self.all_jobs if j.origin == origin), None)

    def has(self, key: str) -> bool:
        return bool(self._jobs.get(key))

    def _launchable(self, key: str, source: str = GenerationSource.GENERATED) -> bool:
        return source != GenerationSource.EXPERIMENT or not self._jobs.get(key)

    def start_prepared(self, key: str, workflow, params: dict, *,
                       source: str = GenerationSource.GENERATED) -> str | None:
        (prompt_id,) = self.start_batch(key, workflow, [params], source=source)
        return prompt_id

    def start_batch(self, key: str, workflow, batch: list[dict], *,
                    source: str = GenerationSource.GENERATED) -> list[str | None]:
        if self._client is None or not self._launchable(key, source):
            return [None] * len(batch)
        jobs = [self._new_job(key, workflow, params, self._on_finished, source=source)
                for params in batch]
        lined_up = [job for job in jobs if job is not None]
        if lined_up:
            self._enqueue(lined_up[0])
            for ahead, job in pairwise(lined_up):
                self._waiting.insert(self._waiting.index(ahead) + 1, job)
            self._admit(lined_up[-1])
        return [job.prompt_id if job is not None and self._key_of(job) == key else None
                for job in jobs]

    def start_reroll(self, key: str, group, image_rows: list[dict]):
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        self._reroll_variation(key, group.rows[0], image_rows, new_image=True, new_video=True)

    def reroll_video_seed(self, key: str, row: dict):
        self._reroll_variation(key, row, (), new_image=False, new_video=True)

    def reroll_image_seed(self, key: str, row: dict, image_rows: list[dict]):
        self._reroll_variation(key, row, image_rows, new_image=True, new_video=False)

    def regenerate(self, key: str, row: dict) -> str | None:
        return self._launch(key, (workflow := WORKFLOW_REGISTRY[row["workflow_name"]]),
                            filled_params(row, workflow), self._on_finished)

    def _reroll_variation(self, key, row, image_rows, *, new_image, new_video):
        if self._client is None or not self._launchable(key):
            return
        if not gallery.rerollable(row):
            return
        workflow = WORKFLOW_REGISTRY[row["workflow_name"]]
        video_params = prepared_params(row, workflow) if new_video else filled_params(row, workflow)
        source = self._reroll_source_image(row, image_rows) if new_image else None
        if source is None:
            if not new_video:
                return
            self._launch(key, workflow, video_params, self._on_finished)
        else:
            source_row, image_workflow = source
            self._launch(
                key, image_workflow, prepared_params(source_row, image_workflow),
                lambda k, job, files, thumb, dur: self._on_image_finished(
                    k, job, (files, thumb, dur), workflow, video_params
                ),
                run_media_type=workflow.output_type,
            )

    def _reroll_source_image(self, row: dict, image_rows: list[dict]):
        picked = gallery.rebuildable_source_image(row, image_rows)
        source = self._db.get_generation(picked["prompt_id"]) if picked is not None else None
        return (source, WORKFLOW_REGISTRY[source["workflow_name"]]) if source is not None else None

    def _launch(self, key, workflow, params, on_finished, *, origin=None, run_media_type=None,
                shielded=False):
        job = self._new_job(key, workflow, params, on_finished,
                            origin=origin, run_media_type=run_media_type, shielded=shielded)
        if job is not None:
            self._enqueue(job)
            self._admit(job)
        return job and job.prompt_id

    def _new_job(self, key, workflow, params, on_finished, *,
                 source=GenerationSource.GENERATED, origin=None, run_media_type=None,
                 shielded=False):
        try:
            job = GenerationJob(self._client, workflow, params, source=source)
        except Exception as e:
            logger.warning("Could not build a re-roll for %s: %s", key, e)
            if _the_users_own(source):
                self.failed.emit(key, f"Origenerator could not put the run together: {e!r}")
            return None
        job.origin = origin or job.prompt_id
        job.run_media_type = run_media_type or job.media_type
        job.shielded = shielded
        start_image = self._enhanced_start_image_of(job)
        if start_image:
            job.start_from(start_image)
        self._register(key, job, on_finished)
        insert_generation_row(self._db, job)
        return job

    def enhance_images_with(self, enhance) -> None:
        self._enhance = enhance

    def _enhanced_start_image_of(self, job: GenerationJob) -> str | None:
        if self._enhance is None or not queue_line.is_video(job) or not job.start_image:
            return None
        start_image = job.params.get("input_image")
        images = [row for row in self._db.list_generations()
                  if gallery.media_type_of_row(row) == MediaType.IMAGE]
        image_id = gallery.source_image_id_for(start_image, images)
        image = next((row for row in images if row["prompt_id"] == image_id), None)
        if image is None:
            return None
        if gallery.is_enhanced_row(image):
            return gallery.enhanced_version_of(start_image, image)
        if not queue_line.waits_for_any(job, self.all_jobs):
            self._enhance(image)
        return None

    def _admit(self, newcomer: GenerationJob):
        if _the_users_own(newcomer.source):
            self._preempt_experiments()
        if queue_line.takes_the_front(newcomer):
            self._image_asked_at = self._clock()
            self._set_aside_for(newcomer)
        self.changed.emit()
        self._pump()
        self.changed.emit()

    def _enqueue(self, job: GenerationJob):
        self._waiting.insert(queue_line.insertion_index(self._waiting, job), job)
        queue_line.put_first(self._waiting, self._first)

    def _pump(self):
        while not self._closed and self._waiting and self._free_for_the_next_job():
            if (wait := self._wait_at_the_front()) > 0:
                self._videos_wait.start(math.ceil(wait * 1000))
                return
            job = self._waiting.pop(0)
            if not self._hand_over(job):
                continue
            newcomer, self._takes_over_on_landing = self._takes_over_on_landing, None
            if newcomer is not None and self._key_of(newcomer) is not None:
                self._set_aside_for(newcomer)

    def start_now(self) -> None:
        self._image_asked_at = None
        self._videos_wait.stop()
        self._pump()

    def starts_at(self, prompt_id: str) -> float | None:
        if (not self._waiting or self._waiting[0].prompt_id != prompt_id
                or not self._free_for_the_next_job()):
            return None
        wait = self._wait_at_the_front()
        return self._clock() + wait if wait > 0 else None

    def _free_for_the_next_job(self) -> bool:
        return not (self._on_server or self._in_flight is not None
                    or self._training_holds_the_line() or self._awaiting_comfyui)

    def _wait_at_the_front(self) -> float:
        since = (None if self._image_asked_at is None
                 else self._clock() - self._image_asked_at)
        return queue_line.wait_before_starting(self._waiting[0], since)

    def _hand_over(self, job: GenerationJob) -> bool:
        key = self._key_of(job)
        self._in_flight = job
        try:
            job.start(None if self._closed else _off_the_gui_thread)
        except Exception as e:
            if self._key_of(job) is None:
                pass
            elif comfyui_api.unreachable(e) and self._closed:
                self._waiting.insert(0, job)
            elif comfyui_api.unreachable(e) and self._bring_up_comfyui is not None:
                self._hold_for_comfyui(job)
            elif self._closed and _the_users_own(job.source):
                logger.warning("Left %s for the next launch to send: ComfyUI refused it as "
                               "the app closed: %s", key, e)
                self._drop(key, job)
            else:
                logger.warning("Re-roll submission failed for %s: %s", key, e)
                self._refuse(key, job, str(e))
            return False
        finally:
            self._in_flight = None
        if job.state == JobState.FINISHED:
            return False
        if self._key_of(job) is None:
            job.cancel()
            return False
        self._on_server.append(job)
        return True

    def _hold_for_comfyui(self, job: GenerationJob) -> None:
        self._waiting.insert(0, job)
        if self._awaiting_comfyui:
            return
        self._awaiting_comfyui = True
        logger.info("ComfyUI did not answer the submit of %s; holding the line until it does",
                    job.prompt_id)
        run_off_thread(self._bring_up_comfyui, self._bring_up_ended, owner=self,
                       waits_long=True)

    def _bring_up_ended(self, came_up) -> None:
        self._awaiting_comfyui = False
        if came_up:
            self._pump()
            return
        logger.warning("ComfyUI could not be brought up; the %d job(s) waiting for it fail",
                       len(self._waiting))
        for job in list(self._waiting):
            self._refuse(self._key_of(job), job, COMFYUI_DID_NOT_START)
        self.changed.emit()

    def _comfyui_unreachable(self, key: str, job: GenerationJob, message: str) -> None:
        if self._bring_up_comfyui is None:
            self._on_failed(key, job, message)
            return
        self._on_server.remove(job)
        self._db.update_generation(job.prompt_id, status=GenerationStatus.PENDING,
                                   progress_json=None)
        self._hold_for_comfyui(job)
        self.changed.emit()

    def _refuse(self, key: str, job: GenerationJob, reason: str) -> None:
        self._db.update_generation(job.prompt_id, status=GenerationStatus.ERROR,
                                   error_message=reason)
        self._drop(key, job)
        if _the_users_own(job.source):
            self.failed.emit(key, reason)

    def flush_to_server(self) -> int:
        self.close()
        if self.training_holds_the_machine():
            logger.info("Left %d queued job(s) for the next launch: a fix's training holds "
                        "the graphics card", len(self._waiting))
            return 0
        handed = 0
        for job in list(self._waiting):
            if queue_line.waits_for_any(job, self.all_jobs):
                continue
            if job.speaks_first and self.making_something():
                logger.info("Kept %s back for whoever comes next: its voice would share the "
                            "graphics card with what ComfyUI is making", job.prompt_id)
                continue
            self._waiting.remove(job)
            if self._hand_over(job):
                handed += 1
            elif self._waiting and self._waiting[0] is job:
                logger.info("Left %d queued job(s) for the next launch: ComfyUI did not answer",
                            len(self._waiting))
                break
        if handed:
            logger.info("Handed ComfyUI %d queued job(s) as the app closed", handed)
        return handed

    def _key_of(self, job: GenerationJob) -> str | None:
        return next((key for key, jobs in self._jobs.items() if job in jobs), None)

    def _drop(self, key: str, job: GenerationJob):
        if job in self._waiting:
            self._waiting.remove(job)
        if job in self._on_server:
            self._on_server.remove(job)
        jobs = self._jobs.get(key)
        if not jobs or job not in jobs:
            return
        jobs.remove(job)
        if not jobs:
            del self._jobs[key]

    def _set_aside_for(self, newcomer: GenerationJob):
        if self._in_flight is not None:
            self._takes_over_on_landing = newcomer
        for job in reversed(list(self._on_server)):
            if (job is newcomer or job.prompt_id in self._first or job.shielded
                    or not job.defer()):
                continue
            self._back_in_the_line(job, queue_line.rejoin_index(self._waiting, job, newcomer))
            logger.info("Set aside %s for the user's image work; it starts over after",
                        job.prompt_id)
        queue_line.put_first(self._waiting, self._first)

    def _back_in_the_line(self, job: GenerationJob, at: int) -> None:
        self._on_server.remove(job)
        self._waiting.insert(at, job)
        self._db.update_generation(job.prompt_id, status=GenerationStatus.PENDING,
                                   progress_json=None)

    def _preempt_experiments(self):
        for jobs in list(self._jobs.values()):
            for job in list(jobs):
                if job.source == GenerationSource.EXPERIMENT and not job.shielded:
                    logger.info(
                        "Preempting background experiment %s for user work", job.prompt_id
                    )
                    self.cancel_job(job.prompt_id)

    def _register(self, key, job, on_finished):
        self._jobs.setdefault(key, []).append(job)
        job.finished.connect(
            lambda files, thumb, dur, k=key, j=job: on_finished(k, j, files, thumb, dur)
        )
        job.sent.connect(lambda j=job: self._db.update_generation(
            j.prompt_id, status=GenerationStatus.RUNNING))
        job.failed.connect(lambda msg, k=key, j=job: self._on_failed(k, j, msg))
        job.unreachable.connect(lambda msg, k=key, j=job: self._comfyui_unreachable(k, j, msg))
        job.preview.connect(
            lambda data, k=key, j=job: self.preview.emit(k, j.prompt_id, data)
        )
        job.progress.connect(lambda *_, j=job: self._persist_progress(j))

    def _persist_progress(self, job: GenerationJob):
        now = time.monotonic()
        if now - self._progress_persist_at.get(job.prompt_id, 0.0) < _PROGRESS_PERSIST_INTERVAL_S:
            return
        self._progress_persist_at[job.prompt_id] = now
        try:
            self._db.update_generation(
                job.prompt_id, progress_json=json.dumps(job.progress_state())
            )
        except Exception as e:
            logger.debug("Could not persist progress for %s: %s", job.prompt_id, e)

    def reconnect_running(self):
        if self._client is None:
            return
        index = gallery.image_config_index_of(self._db.list_generations())
        readopted = []
        making = self._what_comfyui_is_making()
        for row in reversed(self._db.list_generations()):
            if row.get("status") == GenerationStatus.RUNNING:
                job = self._reconnect(row, index)
                if (job is not None and making is not None and job.prompt_id not in making
                        and not job.shielded and job.defer()):
                    self._back_in_the_line(job, queue_line.insertion_index(self._waiting, job))
                    logger.info("Took %s back from ComfyUI's queue into the line", job.prompt_id)
            elif row.get("status") == GenerationStatus.PENDING:
                readopted.append(self._readopt(row, index))
        for job in filter(None, readopted):
            if start_image := self._enhanced_start_image_of(job):
                self._start_from(job, start_image)
        self._pump()
        self.changed.emit()

    def _what_comfyui_is_making(self) -> set[str] | None:
        try:
            return set(self._client.executing_prompts())
        except Exception as e:
            logger.warning("Left ComfyUI's queue as it was: could not read what it is making: %s",
                           e)
            return None

    def _reconnect(self, row: dict, image_index: dict):
        key = gallery.settings_folder_key(row, image_index)
        if self.job_for_prompt(row["prompt_id"]) is not None:
            return None
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return None
        params = gallery.parse_params(row.get("params_json"))
        try:
            job = GenerationJob.reconnect(
                self._client, workflow, params, row["prompt_id"],
                progress_state=_parse_progress_state(row.get("progress_json")),
                source=source_of(row),
            )
        except Exception as e:
            logger.warning("Could not reconnect re-roll for %s: %s", key, e)
            return None
        self._take_back(key, job, row)
        self._on_server.append(job)
        return job

    def _readopt(self, row: dict, image_index: dict):
        key = gallery.settings_folder_key(row, image_index)
        if self.job_for_prompt(row["prompt_id"]) is not None:
            return None
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        try:
            if workflow is None:
                raise ValueError(f"unknown workflow {row.get('workflow_name')!r}")
            job = GenerationJob(
                self._client, workflow, gallery.parse_params(row.get("params_json")),
                prompt_id=row["prompt_id"], source=source_of(row),
            )
        except Exception as e:
            logger.warning("Dropping a queued generation we can no longer build: %s", e)
            self._db.delete_generation(row["prompt_id"])
            return None
        self._take_back(key, job, row)
        self._enqueue(job)
        return job

    def _take_back(self, key: str, job: GenerationJob, row: dict):
        job.origin = job.prompt_id
        job.shielded = bool(row.get("shielded"))
        self._register(key, job, self._on_finished)

    @property
    def queue_order(self) -> list[str]:
        return [job.prompt_id for job in self._line()]

    def _line(self) -> list[GenerationJob]:
        making_first = sorted(self._on_server, key=lambda job: job.state != JobState.RUNNING)
        return making_first + self._waiting

    def joins_before(self, media_type: str) -> str | None:
        newcomer = SimpleNamespace(media_type=media_type, prompt_id=None)
        line = list(self._waiting)
        line.insert(queue_line.insertion_index(line, newcomer), newcomer)
        queue_line.put_first(line, self._first)
        behind = line[line.index(newcomer) + 1:]
        return behind[0].prompt_id if behind else None

    def move(self, prompt_id: str, before: str | None) -> None:
        line = self._line()
        job = _named(line, prompt_id)
        if job is not None:
            self._take_up(self._moved(line, job, _named(line, before)))

    def move_up(self, prompt_id: str) -> None:
        self._take_up(self._one_step(prompt_id, up=True))

    def move_down(self, prompt_id: str) -> None:
        self._take_up(self._one_step(prompt_id, up=False))

    def can_move_up(self, prompt_id: str) -> bool:
        return self._one_step(prompt_id, up=True) is not None

    def can_move_down(self, prompt_id: str) -> bool:
        return self._one_step(prompt_id, up=False) is not None

    def _one_step(self, prompt_id: str, *, up: bool) -> list[GenerationJob] | None:
        line = self._line()
        job = _named(line, prompt_id)
        if job is None:
            return None
        at = line.index(job)
        if up:
            ahead = [other for other in reversed(line[:at])
                     if not queue_line.waits_for(job, other)]
            return self._moved(line, job, ahead[0]) if ahead else None
        behind = [other for other in line[at + 1:] if not queue_line.waits_for(other, job)]
        if not behind:
            return None
        after = line.index(behind[0]) + 1
        return self._moved(line, job, line[after] if after < len(line) else None)

    def _moved(self, line: list[GenerationJob], job: GenerationJob,
               before: GenerationJob | None) -> list[GenerationJob] | None:
        if self._holds_its_place(job):
            return None
        order = sorted(queue_line.moved(line, job, before),
                       key=lambda other: not self._holds_its_place(other))
        return None if order == line else order

    def _holds_its_place(self, job: GenerationJob) -> bool:
        return job.prompt_id in self._first or (job in self._on_server and job.shielded)

    def _take_up(self, order: list[GenerationJob] | None) -> None:
        if order is None:
            return
        first_waiting = next((at for at, job in enumerate(order) if job not in self._on_server),
                             len(order))
        set_aside = False
        for job in order[first_waiting:]:
            if job in self._on_server and job.defer():
                self._back_in_the_line(job, 0)
                set_aside = True
                logger.info("Set aside %s for a job moved ahead of it; it starts over after",
                            job.prompt_id)
        place = {job.prompt_id: at for at, job in enumerate(order)}
        self._waiting.sort(key=lambda job: place[job.prompt_id])
        if set_aside:
            self.start_now()
        else:
            self._pump()
        self.reordered.emit()

    def shield(self, prompt_id: str, shielded: bool) -> None:
        job = self.job_for_prompt(prompt_id)
        if job is None:
            return
        job.shielded = shielded
        self._db.set_shielded(prompt_id, shielded)
        if not shielded and job in self._on_server and self._waiting:
            front = self._waiting[0]
            if queue_line.takes_the_front(front) or front.prompt_id in self._first:
                self._set_aside_for(front)
                self._pump()

    def put_first(self, prompt_ids):
        self._first = frozenset(prompt_ids)
        queue_line.put_first(self._waiting, self._first)
        if self._waiting and self._waiting[0].prompt_id in self._first:
            self._set_aside_for(self._waiting[0])
        self._pump()

    def cancel(self, key: str):
        job = self.job_for(key)
        if job is not None:
            self.cancel_job(job.prompt_id)

    def cancel_job(self, prompt_id: str):
        job = self.job_for_prompt(prompt_id)
        if job is None:
            return
        for stopped in [job, *self._videos_waiting_for(job)]:
            self._drop(self._key_of(stopped), stopped)
            stopped.cancel()
            record_unfinished_run(self._db, stopped, SeedUseKind.CANCELED)
            self._db.delete_generation(stopped.prompt_id)
        self._pump()

    def _on_image_finished(self, key, image_job, landed, video_workflow, video_params):
        files, _thumb_path, _duration = landed
        self._drop(key, image_job)
        mark_generation_completed(self._db, image_job.prompt_id, *landed)
        input_ref = gallery.output_file_reference(files)
        if input_ref is not None:
            video_params = {**video_params, "input_image": input_ref}
        self._launch(key, video_workflow, video_params, self._on_finished,
                     origin=image_job.origin, shielded=image_job.shielded)
        self._pump()

    def _on_finished(self, key, job, files, thumb_path, duration):
        self._drop(key, job)
        waited_on = self._start_waiting_videos_from(job, files)
        if not waited_on:
            self._pump()
        mark_generation_completed(self._db, job.prompt_id, files, thumb_path, duration)
        outcome = _outcome_of(self._db, job, ok=True, seconds=duration)
        self.finished.emit(key, job.prompt_id, job.origin)
        self.run_ended.emit(outcome)
        if waited_on:
            self._pump()

    def _start_waiting_videos_from(self, enhance, files) -> bool:
        enhanced = gallery.output_file_reference(files)
        if enhanced is None or not enhance.enhances:
            return False
        waiting = self._videos_waiting_for(enhance)
        for job in waiting:
            self._start_from(job, enhanced)
        return bool(waiting)

    def _start_from(self, job: GenerationJob, start_image: str):
        job.start_from(start_image)
        self._db.set_params_and_workflow(job.prompt_id, params_json=json.dumps(job.params),
                                         workflow_json=json.dumps(job.payload))

    def _on_failed(self, key, job, message):
        ended = [(key, job, message)] + [
            (self._key_of(video), video, f"Its start image could not be enhanced: {message}")
            for video in self._videos_waiting_for(job)]
        for ended_key, ended_job, _message in ended:
            self._drop(ended_key, ended_job)
        self._pump()
        for ended_key, ended_job, why in ended:
            record_unfinished_run(self._db, ended_job, SeedUseKind.FAILED)
            self._db.update_generation(ended_job.prompt_id, status=GenerationStatus.ERROR,
                                       error_message=why)
            logger.warning("Re-roll failed for %s: %s", ended_key, why)
            self.failed.emit(ended_key, why)
            self.run_ended.emit(_outcome_of(self._db, ended_job, ok=False))

    def _videos_waiting_for(self, enhancement) -> list[GenerationJob]:
        return [job for job in self._waiting if queue_line.waits_for(job, enhancement)]
