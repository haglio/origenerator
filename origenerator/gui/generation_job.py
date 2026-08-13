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

from origenerator.completion import extract_completion
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR
from origenerator.progress import ProgressTracker

logger = logging.getLogger(__name__)

# What a run that ended without writing a file records as its failure. ComfyUI
# ends an interrupted prompt exactly as it ends a successful one — an "executing"
# frame with no node — and its history then carries no outputs, so a cancel that
# didn't come from this job's own cancel() (ComfyUI's own UI, a second app
# instance, an experiment sweep's /interrupt) arrives here looking like a
# completion. Recording it as one would leave a generation the app believes
# exists with nothing on disk: invisible in the gallery, yet enough to make a
# re-run of those settings look like a duplicate and be refused.
_NO_OUTPUT_MESSAGE = "The run ended without producing an output file (interrupted)"


def insert_generation_row(db, job):
    """Insert a :class:`GenerationJob`'s config as a new row (status ``pending``).

    A re-roll tracked from submit inserts its row up front so a restart mid-run can
    find it and reconnect; it's finished with :func:`mark_generation_completed`.
    The row's ``source`` comes from the job itself, so the row and the live job
    can never disagree about who asked for the run.
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
        source=job.source,
    )


def mark_generation_completed(db, prompt_id, files, thumb_path, duration):
    """Update an existing row with a finished job's output files/thumbnail/time."""
    fields = dict(
        status="completed",
        output_files=json.dumps(files),
        thumbnail_path=thumb_path,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    if duration is not None:
        fields["duration_seconds"] = duration
    db.update_generation(prompt_id, **fields)


class GenerationJob(QObject):
    started = pyqtSignal()                       # first activity for our prompt
    progress = pyqtSignal(int, int)             # value, max
    preview = pyqtSignal(bytes)                 # live preview frame (encoded image)
    finished = pyqtSignal(list, object, object)  # output_files, thumb_path|None, duration|None
    failed = pyqtSignal(str)                     # error message

    def __init__(self, client, workflow, params, *, source="generated",
                 output_dir=COMFYUI_OUTPUT_DIR, thumb_dir=THUMB_DIR, parent=None):
        super().__init__(parent)
        self._client = client
        self.workflow = workflow
        self.params = dict(params)
        # Who asked for this run: "generated" for the user's own work,
        # "experiment" for a background experiment's. Kept on the job (not just
        # the DB row) so the controller can tell a preemptible experiment from
        # user work it must never cancel.
        self.source = source
        self.payload = workflow.build_api_payload(self.params)
        self.prompt_id = str(uuid.uuid4())  # our id; also ComfyUI's, and the DB row key
        self._output_dir = output_dir
        self._thumb_dir = thumb_dir
        self._state = "idle"  # idle -> queued -> running -> finished/failed/canceled
        # Fold ComfyUI's per-pass sampler progress into one 0-to-total ramp, so a
        # multi-stage video job doesn't report a bar that resets between passes.
        self._progress_tracker = ProgressTracker.for_payload(self.payload)
        self._last_progress = (0, 0)
        self._last_preview: bytes | None = None
        # How many ComfyUI prompts are ahead of this one, as of the last
        # refresh_backlog; None while it isn't waiting on any.
        self._queued_behind: int | None = None

    # --- state, exposed so a freshly-built tile can rebind to a running job --

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_progress(self) -> tuple[int, int]:
        return self._last_progress

    @property
    def last_preview(self) -> bytes | None:
        return self._last_preview

    @property
    def queued_behind(self) -> int | None:
        """How many ComfyUI prompts sit in front of this job, or ``None`` when it
        isn't waiting on any — read by whatever displays the job."""
        return self._queued_behind

    def refresh_backlog(self) -> None:
        """Re-read how much of ComfyUI's queue is ahead of this job.

        A caller that polls invokes this while the job waits. ComfyUI is a shared
        server that outlives the app, so what's holding a submit up is often work
        this session never launched — another Origenerator instance, another app —
        and with no number for it the wait can't be told apart from a hang. A job
        ComfyUI has already started reports nothing to wait on.
        """
        if self._state != "queued":
            self._queued_behind = None
            return
        try:
            self._queued_behind = self._client.queue_backlog(self.prompt_id)
        except Exception as e:
            logger.debug("Could not read the queue position of %s: %s", self.prompt_id, e)
            self._queued_behind = None

    def progress_state(self) -> dict:
        """A JSON-able snapshot of this job's live progress, to persist on its row.

        Restored on :meth:`reconnect` so a restart mid-run resumes the bar at its
        last position. Carries the displayed ``(cumulative, total)`` and the tracker's
        internal ramp, so even a job with no recognized sampler (raw per-node numbers,
        no ramp) still restores its last shown value.
        """
        return {
            "last_progress": list(self._last_progress),
            "tracker": self._progress_tracker.snapshot(),
        }

    def _restore_progress(self, state: dict) -> None:
        """Seed ``_last_progress`` and the tracker from a persisted snapshot."""
        tracker = state.get("tracker")
        if isinstance(tracker, dict):
            self._progress_tracker.restore(tracker)
        last = state.get("last_progress")
        if isinstance(last, (list, tuple)) and len(last) == 2:
            self._last_progress = (int(last[0]), int(last[1]))

    # --- lifecycle ---------------------------------------------------------

    @classmethod
    def reconnect(cls, client, workflow, params, prompt_id, *, progress_state=None, **kwargs):
        """Rebind to a job already running in ComfyUI under ``prompt_id``.

        Used after a restart to pick a re-roll back up from its persisted running
        row without re-submitting it: the job attaches to the client's signals and
        reports as running, so its progress, preview and completion flow through
        exactly as they would for a job started this session.

        ``progress_state`` (a :meth:`progress_state` snapshot persisted while the job
        last ran) seeds the resumed job's progress, so the bar shows its last position
        at once instead of an indeterminate spin until ComfyUI's next per-step push.
        """
        job = cls(client, workflow, params, **kwargs)
        job.prompt_id = prompt_id
        if progress_state:
            job._restore_progress(progress_state)
        job._attach()
        job._state = "running"
        return job

    def start(self):
        """Submit the job and begin tracking it. Raises if the submit fails."""
        if self._state != "idle":
            return
        self._attach()
        try:
            self._client.submit_job(self.payload, self.prompt_id)
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
            elif self._state == "queued":
                self._client.cancel_prompt(self.prompt_id)
        except Exception as e:
            logger.warning("Failed to cancel job %s: %s", self.prompt_id, e)
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
        if self._state not in ("queued", "running"):
            return
        try:
            history = self._client.fetch_history(self.prompt_id)
        except Exception as e:
            logger.debug("Reconcile fetch failed for %s: %s", self.prompt_id, e)
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
        return prompt_id == self.prompt_id

    def _mark_running(self):
        if self._state == "queued":
            self._state = "running"
            self._queued_behind = None  # it's ours now: nothing left in front of it
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

        A run that produced no file didn't finish, so it fails instead — see
        :data:`_NO_OUTPUT_MESSAGE`.
        """
        if self._state not in ("queued", "running"):
            return
        self._detach()
        # Thumbnail and duration are best-effort inside extract_completion — a
        # failure in either yields None rather than stranding a real completion.
        files, thumb, duration = extract_completion(
            self.workflow, history_data, self._output_dir, self._thumb_dir,
            self.prompt_id, params=self.params,
        )
        if not files:
            self._state = "failed"
            self.failed.emit(_NO_OUTPUT_MESSAGE)
            return
        self._state = "finished"
        self.finished.emit(files, thumb, duration)

    def _on_error(self, prompt_id: str, message: str):
        if not self._is_mine(prompt_id):
            return
        self._detach()
        self._state = "failed"
        self.failed.emit(message)
