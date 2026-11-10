from __future__ import annotations

import contextlib
import logging
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app_support.comfy_file_refs import frame_name
from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import comfyui_api, speech
from origenerator.completion import animate_before_filing, extract_completion
from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW
from origenerator.generation_state import GenerationSource
from origenerator.gui.job_speaker import Speaker
from origenerator.gui.job_spec import NO_FOLDERS, JobFolders, JobSpec
from origenerator.gui.off_thread import run_off_thread
from origenerator.library_filing import saving_into_its_run_folder
from origenerator.media import MediaType
from origenerator.output_places import OutputFolders
from origenerator.progress import SAME_PASS_AS_BEFORE, ProgressTracker, stage_names


@dataclass(frozen=True)
class JobPlan:
    workflow: object
    params: dict
    source: str = GenerationSource.GENERATED
    origin: str | None = None
    run_media_type: str | None = None
    shielded: bool = False


class JobState(StrEnum):
    IDLE = "idle"
    SPEAKING = "speaking"
    QUEUED = "queued"
    RUNNING = "running"
    FINISHING = "finishing"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELED = "canceled"


def display_status(status: str) -> JobState:
    if status == JobState.FINISHING:
        return JobState.RUNNING
    if status in (JobState.SPEAKING, JobState.RUNNING):
        return JobState(status)
    return JobState.QUEUED


logger = logging.getLogger(__name__)

# ComfyUI ends an interrupted prompt exactly as it ends a successful one, with no outputs in its history.
_NO_OUTPUT_MESSAGE = "The run ended without producing an output file (interrupted)"


class GenerationJob(QObject):
    started = pyqtSignal()
    sent = pyqtSignal()
    progress = pyqtSignal(int, int)
    preview = pyqtSignal(bytes)
    finished = pyqtSignal(list, object, object)
    failed = pyqtSignal(str)
    unreachable = pyqtSignal(str)

    def __init__(self, client, spec: JobSpec, folders: JobFolders = NO_FOLDERS, *,
                 speaker=None, run=None):
        super().__init__()
        self._client = client
        self._run = run or run_off_thread
        self.workflow = spec.workflow
        self.params = dict(spec.params)
        self._input_dir = folders.input_dir
        self._speaker = speaker or Speaker(client)
        self.source = spec.source
        self.prompt_id = spec.prompt_id or str(uuid.uuid4())
        self._places = folders.places
        self.payload = self._payload_for(self.params)
        self.origin = self.prompt_id
        self.run_media_type = self.media_type
        self.shielded = False
        self._thumb_dir = folders.thumb_dir
        self._state = JobState.IDLE
        self._stages = stage_names(self.payload)
        self._forget_the_run()

    def _forget_the_run(self):
        self._progress_tracker = ProgressTracker.for_payload(self.payload)
        self._last_progress = (0, 0)
        self._last_pass_progress: tuple[int, int] | None = None
        self._last_stage = ""
        self._last_preview: bytes | None = None
        self._started_at: float | None = None
        self._foreign_ahead: int | None = None

    @property
    def state(self) -> JobState:
        return self._state

    @property
    def media_type(self) -> str:
        return self.workflow.output_type

    @property
    def start_image(self) -> str:
        return frame_name(self.params.get("input_image"))

    @property
    def speaks_first(self) -> bool:
        return bool(speech.missing_speech(self.params, self._input_dir))

    @property
    def enhances(self) -> str:
        return self.start_image if self.workflow.name == ENHANCE_WORKFLOW else ""

    @property
    def last_progress(self) -> tuple[int, int]:
        return self._last_progress

    @property
    def last_pass_progress(self) -> tuple[int, int] | None:
        return self._last_pass_progress

    @property
    def last_stage(self) -> str:
        return self._last_stage

    @property
    def last_preview(self) -> bytes | None:
        return self._last_preview

    @property
    def thumb_dir(self) -> Path:
        return self._thumb_dir

    @property
    def started_at(self) -> float | None:
        return self._started_at

    @property
    def foreign_ahead(self) -> int | None:
        return self._foreign_ahead

    def take_backlog(self, foreign_ahead: int | None) -> None:
        self._foreign_ahead = foreign_ahead if self._state == JobState.QUEUED else None

    def take_executing(self, executing: bool) -> None:
        if executing:
            self._mark_running()

    def progress_state(self) -> dict:
        return {
            "last_progress": list(self._last_progress),
            "tracker": self._progress_tracker.snapshot(),
            "started_at": self._started_at,
        }

    def _restore_progress(self, state: dict) -> None:
        tracker = state.get("tracker")
        if isinstance(tracker, dict):
            self._progress_tracker.restore(tracker)
            self._note_stage(tracker.get("node") or "")
            self._last_pass_progress = self._progress_tracker.current_pass()
        last = state.get("last_progress")
        match last:
            case [value, maximum]:
                self._last_progress = (int(value), int(maximum))
        started = state.get("started_at")
        if isinstance(started, (int, float)):
            self._started_at = float(started)

    @classmethod
    def reconnect(cls, client, spec: JobSpec, *, progress_state=None, **kwargs):
        job = cls(client, spec, **kwargs)
        if progress_state:
            job._restore_progress(progress_state)
        job._attach()
        job._state = JobState.QUEUED if job.started_at is None else JobState.RUNNING
        return job

    def start(self, submit=None):
        if self._state != JobState.IDLE:
            return
        if not self.speaks_first:
            self._submit(submit)
        elif submit is None:
            self._speaker.speak_here(self.params)
            self._submit(None)
        else:
            self._state = JobState.SPEAKING
            self._speaker.speak(self.params, lambda: self._spoken(submit), self._unspoken)

    def _submit(self, submit):
        self._attach()
        landed: list[dict] = []

        def post():
            history = self._stopped_run_landed()
            if history is not None:
                landed.append(history)
                return
            self._client.submit_job(self.payload, self.prompt_id)

        try:
            post() if submit is None else submit(post)
        except Exception:
            self._detach()
            raise
        if landed:
            self._finish(landed[0])
            return
        self._state = JobState.QUEUED
        self.sent.emit()

    def _stopped_run_landed(self) -> dict | None:
        try:
            history = self._client.fetch_history(self.prompt_id)
            if self.workflow.extract_output_info(history):
                return history
            if history:
                self._client.forget_history(self.prompt_id)
        except Exception as e:
            logger.warning("Could not ask after the stopped run of %s: %s", self.prompt_id, e)
        return None

    def _spoken(self, submit):
        if self._state != JobState.SPEAKING:
            return
        self._state = JobState.IDLE
        try:
            self._submit(submit)
        except Exception as e:
            if comfyui_api.unreachable(e):
                self.unreachable.emit(str(e))
                return
            self._state = JobState.FAILED
            self.failed.emit(str(e))

    def _unspoken(self, message: str):
        if self._state != JobState.SPEAKING:
            return
        self._state = JobState.FAILED
        self.failed.emit(message)

    def cancel(self):
        self._detach()
        self._stop_on_server()
        self._state = JobState.CANCELED

    def defer(self) -> bool:
        if self._state not in (JobState.QUEUED, JobState.RUNNING):
            return False
        self._detach()
        self._stop_on_server()
        self._state = JobState.IDLE
        self._forget_the_run()
        return True

    def start_from(self, image: str) -> None:
        self.params = {**self.params, "input_image": image}
        self.payload = self._payload_for(self.params)
        self._stages = stage_names(self.payload)
        self._forget_the_run()

    def _payload_for(self, params: dict) -> dict:
        return saving_into_its_run_folder(
            self.workflow.payload_for_comfyui(params), self._places, self.prompt_id)

    def _stop_on_server(self):
        """ComfyUI skips a named stop for a prompt it is not executing, so both calls are safe whatever state this job last heard."""
        if self._state not in (JobState.QUEUED, JobState.RUNNING):
            return
        try:
            self._client.cancel_prompt(self.prompt_id)
            self._client.interrupt(self.prompt_id)
        except Exception as e:
            logger.warning("Failed to stop job %s: %s", self.prompt_id, e)

    def reconcile_with(self, history) -> None:
        if history is None or self._state not in (JobState.QUEUED, JobState.RUNNING):
            return
        if self.workflow.extract_output_info(history):
            self._complete(history)

    def _attach(self):
        self._client.progress.connect(self._on_progress)
        self._client.node_executing.connect(self._on_node_executing)
        self._client.preview_image.connect(self._on_preview)
        self._client.job_completed.connect(self._on_completed)
        self._client.job_error.connect(self._on_error)

    def _detach(self):
        for signal, handler in (
            (self._client.progress, self._on_progress),
            (self._client.node_executing, self._on_node_executing),
            (self._client.preview_image, self._on_preview),
            (self._client.job_completed, self._on_completed),
            (self._client.job_error, self._on_error),
        ):
            with contextlib.suppress(TypeError):
                signal.disconnect(handler)

    def _is_mine(self, prompt_id: str) -> bool:
        return prompt_id == self.prompt_id

    def _mark_running(self):
        if self._started_at is None:
            self._started_at = time.time()
        if self._state == JobState.QUEUED:
            self._state = JobState.RUNNING
            self._foreign_ahead = None
            self.started.emit()

    def _on_progress(self, prompt_id: str, node_id: str, value: int, max_val: int):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        self._note_stage(node_id)
        self._last_progress = self._progress_tracker.update(
            value, max_val, node=node_id or SAME_PASS_AS_BEFORE)
        self._last_pass_progress = self._progress_tracker.current_pass()
        self.progress.emit(*self._last_progress)

    def _on_node_executing(self, prompt_id: str, node_id: str):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        self._note_stage(node_id)

    def _note_stage(self, node_id: str) -> None:
        stage = self._stages.get(node_id)
        if stage:
            self._last_stage = stage

    def _on_preview(self, prompt_id: str, data: bytes):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        self._last_preview = data
        self.preview.emit(data)

    def _on_completed(self, prompt_id: str, history_data: dict):
        if not self._is_mine(prompt_id):
            return
        self._complete(history_data)

    def _complete(self, history_data: dict):
        if self._state not in (JobState.QUEUED, JobState.RUNNING):
            return
        self._finish(history_data)

    def _finish(self, history_data: dict):
        self._detach()

        def record_what_it_made(_nothing=None):
            if self._state == JobState.CANCELED:
                return
            files, thumb, duration = extract_completion(
                self.workflow, history_data, OutputFolders(self._places, self._thumb_dir),
                self.prompt_id, params=self.params,
            )
            if not files:
                self._state = JobState.FAILED
                self.failed.emit(_NO_OUTPUT_MESSAGE)
                return
            self._state = JobState.FINISHED
            self.finished.emit(files, thumb, duration)

        if self.media_type != MediaType.VIDEO:
            record_what_it_made()
            return
        self._state = JobState.FINISHING
        workflow, places, thumb_dir, prompt_id = (self.workflow, self._places, self._thumb_dir,
                                                  self.prompt_id)
        self._run(lambda: animate_before_filing(workflow, history_data, places, thumb_dir, prompt_id),
                  record_what_it_made, owner=self)

    def _on_error(self, prompt_id: str, message: str):
        if not self._is_mine(prompt_id):
            return
        self._detach()
        self._state = JobState.FAILED
        self.failed.emit(message)
