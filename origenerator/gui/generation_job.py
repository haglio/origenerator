"""One in-flight generation, tracked independently of any Generate panel.

The gallery re-rolls a folder's settings in place, so it needs to submit a
workflow to ComfyUI and follow it — progress, live preview, completion, cancel —
without a panel or a Generate subtab. This wraps that lifecycle: it filters the
shared client's multiplexed signals down to its own job and reports them as
plain Qt signals. It owns no database or widget state; the caller decides what
to persist and how to display it.

A job is built before it is sent. :meth:`GenerationJob.start` is the moment it
reaches ComfyUI, and until then it is only a job this app is holding — which is
what lets the queue order and gate its own line (see
:mod:`origenerator.queue_line`) rather than take whatever order the server's
queue happens to have.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from enum import StrEnum
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from origenerator import comfyui_api, provenance, speech
from origenerator.completion import extract_completion
from origenerator.config import COMFYUI_INPUT_DIR, OUTPUT_PLACES, SPEECH_PYTHON, THUMB_DIR
from origenerator.file_refs import frame_name
from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW
from origenerator.generation_state import GenerationSource
from origenerator.library_filing import saving_into_its_run_folder
from origenerator.progress import ProgressTracker, stage_names
from origenerator.seed_history import SeedUseKind, output_size
from origenerator.thumbnail import frame_thumbnail


class JobState(StrEnum):
    """Where a job is between being asked for and being done with."""

    IDLE = "idle"
    SPEAKING = "speaking"
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELED = "canceled"


def display_status(status: str) -> JobState:
    """What the line calls a run in flight, from its job's state, or its row's
    status where no job holds it: the database says pending for one waiting to
    be sent, a job says idle or queued for one waiting here or on the server,
    and the line says queued for all three."""
    if status in (JobState.SPEAKING, JobState.RUNNING):
        return JobState(status)
    return JobState.QUEUED


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
        provenance=json.dumps(provenance.at_launch(job.workflow)),
        shielded=job.shielded,
    )


def record_unfinished_run(db, job: GenerationJob, kind: SeedUseKind) -> None:
    if job.source != GenerationSource.GENERATED:
        return
    frame = job.last_preview
    thumbnail = (frame_thumbnail(frame, job.thumb_dir, name=f"{job.prompt_id}_{kind}")
                 if frame else None)
    width, height = output_size(job.workflow.name, job.params) or (None, None)
    for key in job.workflow.seed_keys():
        if job.params.get(key) is not None:
            db.record_seed_use(kind=kind, seed_key=key, seed=int(job.params[key]),
                               media_type=job.workflow.output_type, width=width, height=height,
                               thumbnail_path=str(thumbnail) if thumbnail else None)


class GenerationJob(QObject):
    started = pyqtSignal()                       # first activity for our prompt
    sent = pyqtSignal()                          # ComfyUI has our prompt
    progress = pyqtSignal(int, int)             # value, max
    preview = pyqtSignal(bytes)                 # live preview frame (encoded image)
    finished = pyqtSignal(list, object, object)  # output_files, thumb_path|None, duration|None
    failed = pyqtSignal(str)                     # error message
    unreachable = pyqtSignal(str)                # error message; idle, to be sent again

    def __init__(self, client, workflow, params, *, source=GenerationSource.GENERATED,
                 places=OUTPUT_PLACES, thumb_dir=THUMB_DIR, input_dir=COMFYUI_INPUT_DIR,
                 speaker=None, prompt_id=None, parent=None):
        super().__init__(parent)
        self._client = client
        self.workflow = workflow
        self.params = dict(params)
        # Where ComfyUI reads a story's spoken lines from, and who speaks the
        # ones not spoken yet before the job is sent (see start()).
        self._input_dir = input_dir
        self._speaker = speaker or Speaker(client)
        # Who asked for this run: "generated" for the user's own work,
        # "experiment" for a background experiment's. Kept on the job (not just
        # the DB row) so the controller can tell a preemptible experiment from
        # user work it must never cancel.
        self.source = source
        self.prompt_id = prompt_id or str(uuid.uuid4())  # also ComfyUI's id, and the DB row key
        self._places = places
        self.payload = self._payload_for(self.params)
        # Which run this job belongs to. Its own prompt normally — but a chained
        # i2v is two prompts that are one run to whoever asked for it, so the
        # second stage is given the first's id (see JobQueue._launch).
        self.origin = self.prompt_id
        # What the run this job belongs to will produce, which is not always what
        # this prompt outputs: a chained i2v's first stage draws a still, and that
        # still is the opening of a video. The queue places a job by this, so
        # asking for a video never jumps the images already waiting (see
        # JobQueue._launch and :mod:`origenerator.queue_line`).
        self.run_media_type = self.media_type
        self.shielded = False
        self._thumb_dir = thumb_dir
        # idle -> queued -> running -> finished/failed/canceled; and back to idle
        # from queued or running when the job is set aside (see defer()).
        self._state = JobState.IDLE
        # What the app is doing right now, by the node ComfyUI says it is running
        # (see origenerator.progress.stage_names). Kept rather than recomputed so
        # a node with nothing worth saying about it leaves the last real stage
        # standing instead of blanking the caption between two of them.
        self._stages = stage_names(self.payload)
        self._forget_the_run()

    def _forget_the_run(self):
        """What a job that has not started knows about its run: nothing."""
        # Fold ComfyUI's per-pass sampler progress into one 0-to-total ramp, so a
        # multi-stage video job doesn't report a bar that resets between passes.
        self._progress_tracker = ProgressTracker.for_payload(self.payload)
        self._last_progress = (0, 0)
        self._last_pass_progress: tuple[int, int] | None = None
        self._last_stage = ""
        self._last_preview: bytes | None = None
        # When ComfyUI actually began executing this job — not when it was
        # submitted, which on a busy queue can be many minutes earlier. What the
        # running bar's elapsed count and its estimate of the time left run from.
        self._started_at: float | None = None
        # Jobs another app has in front of this one in ComfyUI, as of the last
        # refresh_backlog; None while nothing foreign is ahead.
        self._foreign_ahead: int | None = None

    # --- state, exposed so a freshly-built tile can rebind to a running job --

    @property
    def state(self) -> JobState:
        return self._state

    @property
    def media_type(self) -> str:
        """What this prompt will output — ``"image"`` or ``"video"``.

        Read off the workflow rather than off any file, since the whole point of
        knowing it is to place the job in the line *before* it has run (see
        :mod:`origenerator.queue_line`).

        What the *run* makes is :attr:`run_media_type`, and the two differ for a
        chained i2v's start frame — an image prompt opening a video. The queue
        reads that one; this is what the prompt itself puts on disk.
        """
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
        """The sampler pass running right now, on its own count — or ``None``
        for a single-pass run, which has nothing the whole-run reading doesn't.

        What a bar draws in the substep progress bar along its foot, so a job made of several
        passes shows how far through *this* fix it is without the reading above
        it having to restart per fix."""
        return self._last_pass_progress

    @property
    def last_stage(self) -> str:
        """What the app is doing right now — "Loading models", "First pass",
        "Decoding frames".

        The bar's caption leads with this. Without it a run said nothing for its
        first minute and more, which on a WAN video is two 14B models coming off
        disk before a single step is reported — and then said only that some
        nameless pass had started over. ``""`` before ComfyUI has named a node.
        """
        return self._last_stage

    @property
    def last_preview(self) -> bytes | None:
        return self._last_preview

    @property
    def thumb_dir(self) -> Path:
        return self._thumb_dir

    @property
    def started_at(self) -> float | None:
        """Epoch seconds at this job's first sign of life from ComfyUI, or
        ``None`` while it's still waiting in the queue."""
        return self._started_at

    @property
    def foreign_ahead(self) -> int | None:
        """Jobs another app has in front of this one in ComfyUI, or ``None`` when
        none are — read by whatever displays the job."""
        return self._foreign_ahead

    def take_backlog(self, foreign_ahead: int | None) -> None:
        """Take a re-read of what another app holds ComfyUI with, ahead of this
        job — fetched by the poll, applied here.

        The poll re-reads this while the job waits. ComfyUI is a shared server
        that outlives the app, so a submit can sit after work this session
        never launched, and with no word of it that wait is indistinguishable
        from a hang. The user's own jobs ahead aren't counted — those are what
        they asked for — and a job ComfyUI has already started waits on nothing,
        so anything fetched for one no longer queued is dropped here.
        """
        self._foreign_ahead = foreign_ahead if self._state == JobState.QUEUED else None

    def take_executing(self, executing: bool) -> None:
        if executing:
            self._mark_running()

    def progress_state(self) -> dict:
        """A JSON-able snapshot of this job's live progress, to persist on its row.

        Restored on :meth:`reconnect` so a restart mid-run resumes the bar at its
        last position. Carries the displayed ``(cumulative, total)`` and the tracker's
        internal ramp, so even a job with no recognized sampler (raw per-node numbers,
        no ramp) still restores its last shown value — plus the moment the run
        began, so the elapsed count carries on from where it really started rather
        than restarting at zero with the app.
        """
        return {
            "last_progress": list(self._last_progress),
            "tracker": self._progress_tracker.snapshot(),
            "started_at": self._started_at,
        }

    def _restore_progress(self, state: dict) -> None:
        """Seed ``_last_progress``, the tracker and the start time from a snapshot."""
        tracker = state.get("tracker")
        if isinstance(tracker, dict):
            self._progress_tracker.restore(tracker)
            # The node the ramp was on names the stage, so a reconnected job says
            # what it is doing from its first repaint rather than staying mute
            # until ComfyUI's next push.
            self._note_stage(tracker.get("node") or "")
            # The substep progress bar along the foot comes back with the ramp, so a
            # reconnected multi-pass job shows which pass it is in rather than a
            # whole bar until its next tick.
            self._last_pass_progress = self._progress_tracker.current_pass()
        last = state.get("last_progress")
        match last:
            case [value, maximum]:
                self._last_progress = (int(value), int(maximum))
        started = state.get("started_at")
        if isinstance(started, (int, float)):
            self._started_at = float(started)

    # --- lifecycle ---------------------------------------------------------

    @classmethod
    def reconnect(cls, client, workflow, params, prompt_id, *, progress_state=None, **kwargs):
        """Rebind to a job ComfyUI holds under ``prompt_id``.

        Used after a restart to pick a re-roll back up from its persisted running
        row without re-submitting it: the job attaches to the client's signals, so
        its progress, preview and completion flow through exactly as they would
        for a job started this session -- being made if it had started, else
        waiting its turn there.

        ``progress_state`` (a :meth:`progress_state` snapshot persisted while the job
        last ran) seeds the resumed job's progress, so the bar shows its last position
        at once instead of an indeterminate spin until ComfyUI's next per-step push.
        """
        job = cls(client, workflow, params, prompt_id=prompt_id, **kwargs)
        if progress_state:
            job._restore_progress(progress_state)
        job._attach()
        job._state = JobState.QUEUED if job.started_at is None else JobState.RUNNING
        return job

    def start(self, submit=None):
        """Submit the job and begin tracking it. Raises if the submit fails.

        The submit is the one call here that waits on the server, and it can
        wait a long time (see ``comfyui_api.submit_job``). ``submit`` is how a
        caller keeps that wait off its own thread: given the callable that
        makes the POST, it runs it wherever it likes and returns once it is
        done, raising what it raised; left ``None``, a story's lines are spoken
        and the POST made right here. Signals are attached before and the state
        set after on the calling thread, so nothing of the job's is touched from
        another.
        """
        if self._state != JobState.IDLE:
            return
        # Off the GUI thread, a story's voice sends the job when it is done, or
        # fails it without ever reaching ComfyUI. Whoever holds the line takes
        # the job as started either way: the machine is busy with its voice,
        # which is that job's own work.
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
        landed: list[dict] = []  # the earlier run's history, if it finished after all

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
        """The history of this job's earlier run if that run finished after all,
        else ``None`` -- and then the server's record of the stopped run is gone.

        The stop that set this job aside may have reached the server after its
        last node had saved: then the run finished, and sending the prompt
        again would make the same file twice. Or it stopped, and left a record
        under this id that every read of the job -- the late-submit follow-up,
        the poll's completion backstop -- would take for the run. A server
        that cannot be asked is taken to hold nothing: a send that then fails
        fails the job as any refused submit does.
        """
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
        """The lines are on disk: send the job, unless it was canceled while
        the voice spoke. A submit refused here has no caller to raise to, so
        it fails the job the way a run that errors does."""
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
        """Stop the job and forget it."""
        self._detach()
        self._stop_on_server()
        self._state = JobState.CANCELED

    def defer(self) -> bool:
        """Take the job off the server to be sent again later, and say whether
        it was -- only a job the server holds can be.

        ComfyUI cannot set a run down and pick it back up, so the run is stopped
        and thrown away, and the job comes back as one that has not started:
        the same prompt, under the same id, to be handed over when its turn
        comes round again (see :meth:`start`, which asks after the stopped run
        first).
        """
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
        """Take the prompt out of the server's line if it is waiting there, and
        stop it by name if it is the one being rendered.

        Both, whatever this job last heard: "running" is what ComfyUI said some
        time ago, and a job rebound after a restart says it either way. The
        server skips a named stop for a prompt it is not executing, so neither
        call can touch anything but this job's own prompt.
        """
        if self._state not in (JobState.QUEUED, JobState.RUNNING):
            return  # never handed over, or already gone: nothing there to stop
        try:
            self._client.cancel_prompt(self.prompt_id)
            self._client.interrupt(self.prompt_id)
        except Exception as e:
            logger.warning("Failed to stop job %s: %s", self.prompt_id, e)

    def reconcile_with(self, history) -> None:
        """Finish this job from an already-fetched /history if its live
        completion was missed.

        The websocket ``job_completed`` is a one-shot: a dropped frame or a
        reconnect at the wrong moment loses it, and the job would then hang and
        its output stay out of the gallery until a restart re-imports it. The
        poll fetches the prompt's /history as a backstop and applies it here —
        once ComfyUI has finished it (its outputs are present), the job
        completes exactly as the signal would have. A no-op with nothing
        fetched (``None``), while the prompt is still queued or running (absent
        from /history), or once the job is already terminal.
        """
        if history is None or self._state not in (JobState.QUEUED, JobState.RUNNING):
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
        for signal, handler in (
            (self._client.progress, self._on_progress),
            (self._client.node_executing, self._on_node_executing),
            (self._client.preview_image, self._on_preview),
            (self._client.job_completed, self._on_completed),
            (self._client.job_error, self._on_error),
        ):
            try:
                signal.disconnect(handler)
            except TypeError:
                pass

    def _is_mine(self, prompt_id: str) -> bool:
        return prompt_id == self.prompt_id

    def _mark_running(self):
        if self._started_at is None:
            self._started_at = time.time()
        if self._state == JobState.QUEUED:
            self._state = JobState.RUNNING
            self._foreign_ahead = None  # it's ours now: nothing left in front of it
            self.started.emit()

    def _on_progress(self, prompt_id: str, node_id: str, value: int, max_val: int):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        self._note_stage(node_id)  # also the reconnect's first word on the stage
        self._last_progress = self._progress_tracker.update(
            value, max_val, node=node_id or None)
        self._last_pass_progress = self._progress_tracker.current_pass()
        self.progress.emit(*self._last_progress)

    def _on_node_executing(self, prompt_id: str, node_id: str):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        self._note_stage(node_id)

    def _note_stage(self, node_id: str) -> None:
        """Take up the stage this node stands for, if it stands for one.

        A node this app has no word for leaves the last stage in place: the run
        is still doing whatever it was doing, and a caption that empties between
        two named stages reads as a run that lost its way.
        """
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
        """Finalize a finished prompt: extract its files and emit ``finished``.

        Shared by the live completion signal and :meth:`reconcile`, and guarded by
        state so whichever reaches a given job first wins and the other is a no-op.
        Thumbnailing and duration parsing are best-effort — a failure there must
        never strand a real completion, so the job still finishes with no thumbnail
        rather than hanging and losing its output.

        A run that produced no file didn't finish, so it fails instead — see
        :data:`_NO_OUTPUT_MESSAGE`.
        """
        if self._state not in (JobState.QUEUED, JobState.RUNNING):
            return
        self._finish(history_data)

    def _finish(self, history_data: dict):
        """:meth:`_complete` past its guard -- for a run a second send finds
        already finished, which no state of the job's own announces."""
        self._detach()
        # Thumbnail and duration are best-effort inside extract_completion — a
        # failure in either yields None rather than stranding a real completion.
        files, thumb, duration = extract_completion(
            self.workflow, history_data, self._places, self._thumb_dir,
            self.prompt_id, params=self.params,
        )
        if not files:
            self._state = JobState.FAILED
            self.failed.emit(_NO_OUTPUT_MESSAGE)
            return
        self._state = JobState.FINISHED
        self.finished.emit(files, thumb, duration)

    def _on_error(self, prompt_id: str, message: str):
        if not self._is_mine(prompt_id):
            return
        self._detach()
        self._state = JobState.FAILED
        self.failed.emit(message)


def _speak(client, params: dict) -> None:
    """ComfyUI asked to give the GPU back first (its resident models would leave
    the voice no room), then every line the settings still lack spoken to disk."""
    try:
        client.free_memory()
    except Exception as e:  # noqa: BLE001 -- a voice with less room, not a failed job
        logger.info("ComfyUI kept its models while the lines were spoken: %s", e)
    speech.ensure_speech_files(params, input_dir=COMFYUI_INPUT_DIR, python=SPEECH_PYTHON)


class _Speaking(QThread):
    def __init__(self, client, params, parent=None):
        super().__init__(parent)
        self._client = client
        self._params = params
        self.error: str | None = None

    def run(self):
        try:
            _speak(self._client, self._params)
        except Exception as e:  # noqa: BLE001 -- reported to the job, whatever it was
            self.error = str(e)


class Speaker(QObject):
    """Speaks a job's lines, on a thread of their own answering on the GUI's, or here.

    ``speak(params, done, failed)`` returns at once; ``done()`` or
    ``failed(message)`` is called on this object's thread when the voice has
    finished, which is what lets a job submit itself from the callback.
    """

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self._client = client
        self._speaking: list[_Speaking] = []  # alive until they answer

    def speak(self, params: dict, done, failed) -> None:
        thread = _Speaking(self._client, params)
        thread.finished.connect(lambda: self._answer(thread, done, failed))
        self._speaking.append(thread)
        thread.start()

    def speak_here(self, params: dict) -> None:
        _speak(self._client, params)

    def _answer(self, thread, done, failed) -> None:
        self._speaking.remove(thread)
        if thread.error is None:
            done()
        else:
            failed(thread.error)
