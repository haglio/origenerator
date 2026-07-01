"""One in-flight generation, tracked independently of any Generate panel.

The gallery re-rolls a folder's settings in place, so it needs to submit a
workflow to ComfyUI and follow it — progress, live preview, completion, cancel —
without a panel or a Generate subtab. This wraps that lifecycle: it filters the
shared client's multiplexed signals down to its own job and reports them as
plain Qt signals. It owns no database or widget state; the caller decides what
to persist and how to display it.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR
from origenerator.progress import ProgressTracker
from origenerator.thumbnail import generate_thumbnail
from origenerator.timing import execution_duration_seconds

logger = logging.getLogger(__name__)


def persist_generation(db, job, files, thumb_path, duration):
    """Record a finished :class:`GenerationJob` as a completed generation.

    Inserts the job's config, then marks it completed with its output files,
    thumbnail and (when known) duration. Shared by the gallery re-roll and the
    Generate tab's random-input step — each produces a generation the app must
    save exactly as if it had been generated through a panel.
    """
    params = job.params
    db.insert_generation(
        prompt_id=job.prompt_id,
        workflow_name=job.workflow.name,
        workflow_version=job.workflow.version,
        positive_prompt=params.get("positive_prompt", ""),
        negative_prompt=params.get("negative_prompt", ""),
        seed=params.get("seed"),
        params_json=json.dumps(params),
        workflow_json=json.dumps(job.payload),
    )
    fields = dict(
        status="completed",
        output_files=json.dumps(files),
        thumbnail_path=thumb_path,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    if duration is not None:
        fields["duration_seconds"] = duration
    db.update_generation(job.prompt_id, **fields)


class GenerationJob(QObject):
    started = pyqtSignal()                       # first activity for our prompt
    progress = pyqtSignal(int, int)             # value, max
    preview = pyqtSignal(bytes)                 # live preview frame (encoded image)
    finished = pyqtSignal(list, object, object)  # output_files, thumb_path|None, duration|None
    failed = pyqtSignal(str)                     # error message

    def __init__(self, client, workflow, params, *,
                 output_dir=COMFYUI_OUTPUT_DIR, thumb_dir=THUMB_DIR, parent=None):
        super().__init__(parent)
        self._client = client
        self.workflow = workflow
        self.params = dict(params)
        self.payload = workflow.build_api_payload(self.params)
        self.prompt_id = str(uuid.uuid4())  # our id; the DB row key when persisted
        self._output_dir = output_dir
        self._thumb_dir = thumb_dir
        self._comfy_id: str | None = None
        self._state = "idle"  # idle -> queued -> running -> finished/failed/canceled
        # Fold ComfyUI's per-pass sampler progress into one 0-to-total ramp, so a
        # multi-stage video job doesn't report a bar that resets between passes.
        self._progress_tracker = ProgressTracker.for_payload(self.payload)
        self._last_progress = (0, 0)
        self._last_preview: bytes | None = None

    # --- state, exposed so a freshly-built tile can rebind to a running job --

    @property
    def comfy_id(self) -> str | None:
        return self._comfy_id

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_progress(self) -> tuple[int, int]:
        return self._last_progress

    @property
    def last_preview(self) -> bytes | None:
        return self._last_preview

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        """Submit the job and begin tracking it. Raises if the submit fails."""
        if self._state != "idle":
            return
        self._attach()
        try:
            self._comfy_id = self._client.submit_job(self.payload)
        except Exception:
            self._detach()
            raise
        self._state = "queued"

    def cancel(self):
        """Stop the job: interrupt it if running, else drop it from the queue."""
        self._detach()
        try:
            if self._state == "running":
                self._client.interrupt()
            elif self._comfy_id:
                self._client.cancel_prompt(self._comfy_id)
        except Exception as e:
            logger.warning("Failed to cancel job %s: %s", self._comfy_id, e)
        self._state = "canceled"

    def detach(self):
        """Stop reacting to the client without touching the server-side job."""
        self._detach()

    def reconcile(self):
        """Finish this job from /history if its live completion was missed.

        The websocket ``job_completed`` is a one-shot: a dropped frame or a
        reconnect at the wrong moment loses it, and the job would then hang and
        its output stay out of the gallery until a restart re-imports it. A caller
        that polls invokes this as a backstop — it pulls the prompt's /history and,
        once ComfyUI has finished it (its outputs are present), completes the job
        exactly as the signal would have. A no-op while the prompt is still queued
        or running (absent from /history) or once the job is already terminal.
        """
        if self._state not in ("queued", "running") or self._comfy_id is None:
            return
        try:
            history = self._client.fetch_history(self._comfy_id)
        except Exception as e:
            logger.debug("Reconcile fetch failed for %s: %s", self._comfy_id, e)
            return
        if self.workflow.extract_output_info(history):
            self._complete(history)

    # --- client signal plumbing -------------------------------------------

    def _attach(self):
        self._client.progress.connect(self._on_progress)
        self._client.node_executing.connect(self._on_node_executing)
        self._client.preview_image.connect(self._on_preview)
        self._client.job_completed.connect(self._on_completed)
        self._client.job_error.connect(self._on_error)

    def _detach(self):
        for signal, slot in (
            (self._client.progress, self._on_progress),
            (self._client.node_executing, self._on_node_executing),
            (self._client.preview_image, self._on_preview),
            (self._client.job_completed, self._on_completed),
            (self._client.job_error, self._on_error),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def _is_mine(self, prompt_id: str) -> bool:
        return self._comfy_id is not None and prompt_id == self._comfy_id

    def _mark_running(self):
        if self._state == "queued":
            self._state = "running"
            self.started.emit()

    def _on_progress(self, prompt_id: str, value: int, max_val: int):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        self._last_progress = self._progress_tracker.update(value, max_val)
        self.progress.emit(*self._last_progress)

    def _on_node_executing(self, prompt_id: str, _node_id: str):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()

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
        """Finalize a finished prompt: extract its files and emit ``finished``.

        Shared by the live completion signal and :meth:`reconcile`, and guarded by
        state so whichever reaches a given job first wins and the other is a no-op.
        Thumbnailing and duration parsing are best-effort — a failure there must
        never strand a real completion, so the job still finishes with no thumbnail
        rather than hanging and losing its output.
        """
        if self._state not in ("queued", "running"):
            return
        self._detach()
        files = self.workflow.extract_output_info(history_data)
        try:
            thumb = self._make_thumbnail(files)
        except Exception as e:
            logger.warning("Thumbnail step failed for %s: %s", self.prompt_id, e)
            thumb = None
        try:
            duration = execution_duration_seconds(history_data)
        except Exception as e:
            logger.warning("Duration parse failed for %s: %s", self.prompt_id, e)
            duration = None
        self._state = "finished"
        self.finished.emit(files, thumb, duration)

    def _on_error(self, prompt_id: str, message: str):
        if not self._is_mine(prompt_id):
            return
        self._detach()
        self._state = "failed"
        self.failed.emit(message)

    def _make_thumbnail(self, files: list) -> str | None:
        if not files:
            return None
        first = files[0]
        source = self._output_dir / first.get("subfolder", "") / first["filename"]
        if not source.exists():
            return None
        try:
            self._thumb_dir.mkdir(parents=True, exist_ok=True)
            return str(generate_thumbnail(
                source, self.workflow.output_type, self._thumb_dir,
                name=self.prompt_id,
            ))
        except Exception as e:
            logger.warning("Thumbnail generation failed for %s: %s", source, e)
            return None
