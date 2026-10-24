"""Every generation this app makes, from the press to the saved row.

Two shapes arrive — a fresh variation of a settings folder (a re-roll) and a
video built from an arbitrary image on another video's recipe (a combine) — and
both are keyed by their settings folder, so a combine reconnects and lands in
its folder exactly as a re-roll does.

The line lives on this side of the wire because that is the only side a job can
be moved on: waiting here it has never been sent, so it can be re-ordered or
dropped for free, where a job already on ComfyUI can only be interrupted. :mod:`origenerator.queue_line` decides the order.

A waiting job gets its database row up front, under the status it will run
with, so a line held overnight survives a restart — :meth:`reconnect_running`
picks the sent ones back up and re-adopts the unsent — and so closing the app
can hand ComfyUI everything left (:meth:`flush_to_server`) rather than take it
to the grave.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time

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
from origenerator.run_notice import RunOutcome
from origenerator.seed_history import SeedUseKind
from origenerator.timing import elapsed_since
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# How often a running job's live progress is written to its row. Throttled because
# progress ticks fire per sampler step (sub-second for images); the persisted value
# only needs to be recent enough that a restart resumes the bar near where it was.
_PROGRESS_PERSIST_INTERVAL_S = 1.0

COMFYUI_DID_NOT_START = "Origenerator couldn't start ComfyUI."


def bring_up_the_comfyui_here() -> bool:
    return comfyui_launcher.bring_up(logger, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_DIR)


BRING_UP_COMFYUI = bring_up_the_comfyui_here


def _outcome_of(db, job, *, ok: bool, seconds: float | None = None) -> RunOutcome:
    """What *job* came to, in the record whoever reports a run reads.

    *seconds* is ComfyUI's own measure of the run, which only a finished one
    has: a prompt that died left no ``execution_success`` to measure to. So a
    failure is timed by the clock it ran under instead, which is the same span
    the bar was counting up while it ran.

    Read before the finish is announced, because the announcement is what folds
    an enhance away (:func:`origenerator.gallery.fold_enhancement`): the row is
    still there to name the picture the run improved.
    """
    return RunOutcome(
        kind=gallery.job_kind_label(job.workflow.name),
        recipe=job.workflow.display_name,
        seconds=elapsed_since(job.started_at) if seconds is None else seconds,
        ok=ok,
        source=job.source,
        generation=_the_item_it_is_about(db, job),
    )


def _the_item_it_is_about(db, job) -> str:
    """The generation a run is a run of, as the gallery will hold it afterwards.

    Its own, except for an enhance: that is an upgrade of a picture already in
    the gallery, and its own row is folded into that picture and deleted as it
    lands, so its id names nothing by the time anyone can answer a notice of it.
    """
    row = db.get_generation(job.prompt_id) or {}
    return row.get("enhance_of") or job.prompt_id


def _off_the_gui_thread(run) -> None:
    """Run ``run`` on a thread of its own and keep the window alive until it
    returns, then raise whatever it raised.

    For the one call in this module that waits on the server: the submit.
    ComfyUI can take a minute to accept a prompt (fifty seconds on 2026-09-05,
    validating a two-scene clip), and the follow-up on a late answer waits
    longer still (``comfyui_api.submit_job``). Made on the GUI thread, that
    wait was the window freezing solid -- no paint, no click -- which reads as
    a crash, and the row the launch had just written could not be shown. So the
    call goes to a thread, and this thread pumps the window's events meanwhile:
    the new row is painted, the poll runs, a Cancel is taken. Still on the
    calling thread's stack, so everything around the wait stays in order and
    every caller of the line stays synchronous; what the pumping lets in is
    handled where it arrives (:meth:`JobQueue._pump` stands down while
    a hand-over is out). Without an application to pump, it just runs.
    """
    app = QCoreApplication.instance()
    if app is None:
        run()
        return
    outcome: list = []

    def target():
        try:
            run()
            outcome.append(None)
        except BaseException as e:  # carried back to the caller's thread
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


def _parse_progress_state(raw):
    """The persisted progress snapshot for a row, or ``None`` when absent/corrupt."""
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return state if isinstance(state, dict) else None


class JobQueue(QObject):
    """The jobs of each settings-folder key, driven to completion, with the
    redraws the view should make emitted along the way.

    A launched job joins the line and is handed to ComfyUI only when the machine
    is free, which is what lets an image jump ahead of a video.

    User work owns the GPU: launching any user job first cancels every in-flight
    background experiment, the one generator of jobs the user didn't ask for, so a
    Generate starts at once instead of queuing after a long experiment run. And the
    user's image work owns it outright: whatever is being rendered when a picture is
    asked for is set aside -- stopped, and put back in the line to start over once
    the pictures are done (:meth:`_set_aside_for`) -- unless a slideshow is locked
    on it (:meth:`put_first`) or it is shielded (:meth:`shield`)."""

    changed = pyqtSignal()            # the set of live jobs changed (add/reconnect)
    # (folder key, prompt_id, frame) a job streamed a frame. Named by run as well
    # as by folder: a folder can have several in flight at once, and a surface
    # that shows the frame as the run itself — a slideshow slide of a generation
    # being made — has to know which of them it just saw.
    preview = pyqtSignal(str, str, bytes)
    # (folder key, prompt_id, origin) a job finished and was saved. The
    # prompt_id tells the view whose completion this is — a background experiment
    # leaves the tabs alone. The origin is the id the run began under (its own,
    # unless a chained i2v carried it across the hand-off), which is how the view
    # finds the tab that launched it — the only tab its result belongs in.
    finished = pyqtSignal(str, str, str)
    failed = pyqtSignal(str, str)     # (folder key, message) a job failed
    # A run ended, as one :class:`~origenerator.run_notice.RunOutcome`. The two
    # signals above say which folder to redraw; this says what the run *was*,
    # which is all anyone reporting it outside the window has to go on — by then
    # there is no tile left to write the news on.
    run_ended = pyqtSignal(object)

    def __init__(self, db, client, parent=None, *, clock=time.monotonic, bring_up_comfyui=None):
        super().__init__(parent)
        self._db = db
        self._client = client
        self._clock = clock
        self._bring_up_comfyui = bring_up_comfyui or BRING_UP_COMFYUI
        self._awaiting_comfyui = False
        self._picture_asked_at: float | None = None
        self._videos_wait = QTimer(self)
        self._videos_wait.setSingleShot(True)
        self._videos_wait.timeout.connect(self._pump)
        self._jobs: dict[str, list[GenerationJob]] = {}  # folder key -> its live jobs
        self._progress_persist_at: dict[str, float] = {}  # prompt_id -> last-write time
        # The queue proper: what ComfyUI is holding for us (one job, normally —
        # more only when a previous session left several), and the line waiting
        # to be handed over, in the order it will be.
        self._on_server: list[GenerationJob] = []
        self._waiting: list[GenerationJob] = []
        self._in_flight: GenerationJob | None = None  # out to the server, unanswered
        # The user's picture asked for while a hand-over was out, which takes
        # the machine from what lands (see _set_aside_for and _pump).
        self._takes_over_on_landing: GenerationJob | None = None
        self._first: frozenset[str] = frozenset()
        self._training = None

    def hold_for_training(self, training) -> None:
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

    def training_holds_the_machine(self) -> bool:
        return self._training is not None and self._training.running

    def making_something(self) -> bool:
        return bool(self._on_server) or self._in_flight is not None

    def free_comfyui_memory(self) -> None:
        self._client.free_memory()

    @property
    def jobs(self) -> dict:
        """The folder-facing view: each folder's *leading* live job, by folder key.

        A folder can have several queued at once, but the things keyed by folder —
        its one generating tile, the selection that follows it — show the one in
        front: being made, or next to be. That is not always the one asked for
        first, since a picture asked for second takes the machine from the first
        (:meth:`_set_aside_for`). Use :attr:`all_jobs` for everything in flight.
        """
        return {key: self._leading(jobs) for key, jobs in self._jobs.items() if jobs}

    @property
    def all_jobs(self) -> list:
        """Every live job, across every folder."""
        return [job for jobs in self._jobs.values() for job in jobs]

    @property
    def jobs_by_folder(self) -> dict:
        """Every live job, grouped by the folder it will land in (read-only view)."""
        return {key: list(jobs) for key, jobs in self._jobs.items()}

    def job_for(self, key: str):
        """The live job leading a folder's queue, or ``None``."""
        jobs = self._jobs.get(key)
        return self._leading(jobs) if jobs else None

    def _leading(self, jobs: list) -> GenerationJob:
        """The one of a folder's jobs nearest the front of the line."""
        place = {pid: index for index, pid in enumerate(self.queue_order)}
        return min(jobs, key=lambda job: (-1 if job is self._in_flight
                                          else place.get(job.prompt_id, len(place))))

    def newest_job_for(self, key: str):
        """The job most recently launched into a folder, or ``None``.

        What a caller that has just launched asks for: :meth:`job_for` would hand
        back whatever was already queued in front of it.
        """
        jobs = self._jobs.get(key)
        return jobs[-1] if jobs else None

    def job_for_prompt(self, prompt_id: str | None):
        """The live job with this prompt id, or ``None`` — it may have finished."""
        return next((j for j in self.all_jobs if j.prompt_id == prompt_id), None)

    def job_for_origin(self, origin: str | None):
        """The live job of the run that began at ``origin``, or ``None``.

        A chained i2v re-roll is two prompts — the frame, then the video on it —
        but one run as far as whoever launched it is concerned, so both carry the
        id of the first. That is what lets a config tab keep showing progress for
        its own Generate across the hand-off (see :meth:`_on_image_finished`).
        """
        if origin is None:
            return None
        return next((j for j in self.all_jobs if j.origin == origin), None)

    def has(self, key: str) -> bool:
        return bool(self._jobs.get(key))

    def _launchable(self, key: str, source: str = GenerationSource.GENERATED) -> bool:
        """Whether a launch may join ``key``.

        A background experiment takes only an idle folder and never stacks; user
        work preempts one in :meth:`_admit`. The user's own batches — Enhance All,
        a folder's settings rewrite — queue one run per picture into a folder that
        is already busy, so a folder holding several jobs is normal here; it is a
        second *press* that the gallery turns down.
        """
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
            for ahead, job in zip(lined_up, lined_up[1:]):
                self._waiting.insert(self._waiting.index(ahead) + 1, job)
            self._admit(lined_up[-1])
        return [job.prompt_id if job is not None and self._key_of(job) == key else None
                for job in jobs]

    def start_reroll(self, key: str, group, image_rows: list[dict]):
        """Launch a fresh variation of the settings folder ``key`` names — both
        seeds re-rolled (a new start frame *and* a new video seed).

        An i2v whose input image is itself a re-buildable generation re-rolls that
        image first (fresh start frame), then runs the video on it; any other row
        just re-rolls its one workflow with the same input, as before.
        """
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        self._reroll_variation(key, group.rows[0], image_rows, new_image=True, new_video=True)

    def reroll_video_seed(self, key: str, row: dict):
        """Re-roll one i2v item keeping its start frame, with a fresh video seed.

        Re-runs the video on the same input image — a new motion of the same frame.
        The image seed is untouched, so no image is regenerated first.
        """
        self._reroll_variation(key, row, (), new_image=False, new_video=True)

    def reroll_image_seed(self, key: str, row: dict, image_rows: list[dict]):
        """Re-roll one i2v item keeping its video seed, on a freshly drawn frame.

        Regenerates the start frame (the source image's settings, a new seed) then
        re-runs the video with this item's *existing* video seed — the same motion
        on a new frame. A no-op when the frame isn't a re-buildable generation
        (nothing to re-roll, and keeping both seeds would just duplicate the item).
        """
        self._reroll_variation(key, row, image_rows, new_image=True, new_video=False)

    def _reroll_variation(self, key, row, image_rows, *, new_image, new_video):
        """Launch ``row``'s recipe with each seed independently re-rolled or kept.

        The video seed is re-rolled (``new_video``) or reused as stored; the start
        frame is freshly regenerated (``new_image``, when it's a re-buildable
        generation) or reused. When neither the frame nor the video seed would
        change, there's nothing to make, so it's a no-op — the guard that keeps an
        image-seed re-roll of a hand-picked (un-rebuildable) frame from duplicating
        the item.
        """
        if self._client is None or not self._launchable(key):
            return  # no client, or this folder already has one running
        if not gallery.rerollable(row):
            return
        workflow = WORKFLOW_REGISTRY[row["workflow_name"]]
        video_params = prepared_params(row, workflow) if new_video else filled_params(row, workflow)
        source = self._reroll_source_image(row, image_rows) if new_image else None
        if source is None:
            if not new_video:
                return  # neither seed changes — nothing to generate
            self._launch(key, workflow, video_params, self._on_finished)
        else:
            source_row, image_workflow = source
            self._launch(
                key, image_workflow, prepared_params(source_row, image_workflow),
                lambda k, job, files, thumb, dur: self._on_image_finished(
                    k, job, files, thumb, dur, workflow, video_params
                ),
                run_media_type=workflow.output_type,  # a frame opening a video
            )

    def _reroll_source_image(self, row: dict, image_rows: list[dict]):
        """The image generation ``row``'s input image came from, paired with its
        workflow, when the app can rebuild it — so an i2v re-roll can regenerate a
        fresh start frame first. ``None`` when there's no reusable source image."""
        picked = gallery.rebuildable_source_image(row, image_rows)
        source = self._db.get_generation(picked["prompt_id"]) if picked is not None else None
        return (source, WORKFLOW_REGISTRY[source["workflow_name"]]) if source is not None else None

    def _launch(self, key, workflow, params, on_finished, *, origin=None, run_media_type=None,
                shielded=False):
        """``origin`` is the prompt id the run began under, carried across a chained
        i2v's image→video hand-off so both stages read as one run. ``run_media_type``
        is what that whole run makes, for a stage that doesn't make it itself: the
        chain's first prompt draws a still, and the line must place it as the video
        it was asked for, or asking for a video would jump every picture already
        waiting.
        """
        job = self._new_job(key, workflow, params, on_finished,
                            origin=origin, run_media_type=run_media_type, shielded=shielded)
        if job is not None:
            self._enqueue(job)
            self._admit(job)

    def _new_job(self, key, workflow, params, on_finished, *,
                 source=GenerationSource.GENERATED, origin=None, run_media_type=None,
                 shielded=False):
        """The job joins the line rather than the server: its row is written first
        (``pending``, the row it will run under) so a restart can find it either
        way, and :meth:`_pump` hands it over when its turn comes."""
        try:
            job = GenerationJob(self._client, workflow, params, source=source)
        except Exception as e:
            logger.warning("Could not build a re-roll for %s: %s", key, e)
            if _the_users_own(source):
                self.failed.emit(key, f"Origenerator could not put the run together: {e!r}")
            return None
        job.origin = origin or job.prompt_id  # a chained stage keeps the first id
        job.run_media_type = run_media_type or job.media_type
        job.shielded = shielded
        self._register(key, job, on_finished)
        insert_generation_row(self._db, job)
        return job

    def _admit(self, newcomer: GenerationJob):
        """User work preempts a background experiment here, at the one choke point
        every user path funnels through — so a Generate never sits after an
        experiment's run (see :meth:`_preempt_experiments`)."""
        # Preempted after this job is in the line, not before: dropping an
        # experiment frees the machine and starts whatever is at the front, and
        # the front has to be this job by then or the wait it was preempted for
        # is just handed to something else.
        if newcomer.source != GenerationSource.EXPERIMENT:
            self._preempt_experiments()
        if queue_line.takes_the_front(newcomer):
            self._picture_asked_at = self._clock()
            self._set_aside_for(newcomer)
        # Announced before the hand-over, not after: the server can take a
        # minute to answer, and the launch is in the line the moment its row is
        # written, so that is when its tile appears.
        self.changed.emit()
        self._pump()
        self.changed.emit()

    # --- the line: joining it, and being handed over ------------------------

    def _enqueue(self, job: GenerationJob):
        """Put a built job in the line, wherever the queue's rules place it."""
        self._waiting.insert(queue_line.insertion_index(self._waiting, job), job)
        queue_line.put_first(self._waiting, self._first)

    def _pump(self):
        """Hand ComfyUI the next job it may start, if it isn't holding one of ours.

        One at a time: the whole reason the line is kept here is that a prompt
        already on the server can no longer be re-ordered or held back, so
        nothing is sent until the machine is free to run it. A submit that fails
        takes that job out of the line and the next one is tried, rather than the
        queue stalling on a job the server refuses. While a hand-over is out --
        its submit unanswered, the window alive meanwhile -- nothing else moves:
        whatever asked is answered when it lands, by the loop that sent it.
        """
        while self._waiting and self._free_for_the_next_job():
            if (wait := self._wait_at_the_front()) > 0:
                self._videos_wait.start(math.ceil(wait * 1000))
                return
            job = self._waiting.pop(0)
            if not self._hand_over(job):
                continue
            # A picture asked for while that hand-over was out takes the machine
            # from what just landed on it, as one asked for a moment later would.
            newcomer, self._takes_over_on_landing = self._takes_over_on_landing, None
            if newcomer is not None and self._key_of(newcomer) is not None:
                self._set_aside_for(newcomer)

    def start_now(self) -> None:
        self._picture_asked_at = None
        self._videos_wait.stop()
        self._pump()

    def starts_at(self, prompt_id: str) -> float | None:
        """When ``prompt_id`` starts, on this clock, if only the minute's wait holds it."""
        if (not self._waiting or self._waiting[0].prompt_id != prompt_id
                or not self._free_for_the_next_job()):
            return None
        wait = self._wait_at_the_front()
        return self._clock() + wait if wait > 0 else None

    def _free_for_the_next_job(self) -> bool:
        return not (self._on_server or self._in_flight is not None or self._training is not None
                    or self._awaiting_comfyui)

    def _wait_at_the_front(self) -> float:
        since = (None if self._picture_asked_at is None
                 else self._clock() - self._picture_asked_at)
        return queue_line.wait_before_starting(self._waiting[0], since)

    def _hand_over(self, job: GenerationJob, *, closing: bool = False) -> bool:
        """Submit one job to ComfyUI, reporting whether the server took it.

        The submit waits off the GUI thread with the window kept alive
        (:func:`_off_the_gui_thread`), so a Cancel can arrive while it is out:
        the job is gone from the line by the time the server answers, and a
        server that took it is told to let it go. A refused run of the user's
        says so through :attr:`failed`. The ``closing`` app has no window
        left to keep alive, so it makes the plain blocking call.
        """
        key = self._key_of(job)
        self._in_flight = job
        try:
            job.start(None if closing else _off_the_gui_thread)
        except Exception as e:
            if self._key_of(job) is None:
                return False  # canceled while out, and never taken: nothing to undo
            if self._bring_up_comfyui is not None and comfyui_api.unreachable(e) and not closing:
                self._wait_for_comfyui(job)
                return False
            logger.warning("Re-roll submission failed for %s: %s", key, e)
            self._refuse(key, job, str(e))
            return False
        finally:
            self._in_flight = None
        if job.state == JobState.FINISHED:
            # A job set aside whose stopped run had finished after all: nothing
            # was sent, and its landing has already been recorded through its
            # own finished signal (see GenerationJob.start).
            return False
        if self._key_of(job) is None:
            job.cancel()  # canceled while out; the server has it and must not run it
            return False
        self._on_server.append(job)
        self._db.update_generation(job.prompt_id, status=GenerationStatus.RUNNING)
        return True

    def _wait_for_comfyui(self, job: GenerationJob) -> None:
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

    def _refuse(self, key: str, job: GenerationJob, reason: str) -> None:
        self._db.update_generation(job.prompt_id, status=GenerationStatus.ERROR,
                                   error_message=reason)
        self._drop(key, job)
        if _the_users_own(job.source):
            self.failed.emit(key, reason)

    def flush_to_server(self) -> int:
        """Hand ComfyUI everything still waiting, and say how much went.

        What the closing app calls. ComfyUI outlives Origenerator and works
        through its queue alone, so a line kept for the user's sake — including
        the batch of experiments the close just queued — belongs to the server
        the moment there is no longer a user to keep it for. Every rule this
        queue has is about not interrupting somebody who is watching.
        """
        if self.training_holds_the_machine():
            logger.info("Left %d queued job(s) for the next launch: a fix's training holds "
                        "the graphics card", len(self._waiting))
            return 0
        handed = 0
        for job in list(self._waiting):
            self._waiting.remove(job)
            if self._hand_over(job, closing=True):
                handed += 1
        if handed:
            logger.info("Handed ComfyUI %d queued job(s) as the app closed", handed)
        return handed

    def _key_of(self, job: GenerationJob) -> str | None:
        """The folder key a job was launched under, or ``None`` if it's untracked."""
        return next((key for key, jobs in self._jobs.items() if job in jobs), None)

    def _drop(self, key: str, job: GenerationJob):
        """Forget one job — its place in the line included — and the folder's
        entry once its last one is gone."""
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
        """Take everything but what is put first or shielded off the server for
        ``newcomer``, and put each job back in the line to start over once the
        newcomer is done (:mod:`origenerator.queue_line` says why).

        Each job goes back where :func:`queue_line.rejoin_index` says, placed
        last to first so that several (a restart can leave the server holding
        more than one) keep their order. A job whose hand-over is still out
        cannot be taken off a server that does not hold it yet: it is taken off
        the moment it lands (see :meth:`_pump`).
        """
        if self._in_flight is not None:
            self._takes_over_on_landing = newcomer
        for job in reversed(list(self._on_server)):
            if (job is newcomer or job.prompt_id in self._first or job.shielded
                    or not job.defer()):
                continue
            self._on_server.remove(job)
            self._waiting.insert(queue_line.rejoin_index(self._waiting, job, newcomer), job)
            # Back to pending: a restart re-adopts a pending row into the line,
            # where a running one is looked for on a server that no longer has it.
            self._db.update_generation(job.prompt_id, status=GenerationStatus.PENDING,
                                       progress_json=None)
            logger.info("Set aside %s for the user's image work; it starts over after",
                        job.prompt_id)
        queue_line.put_first(self._waiting, self._first)

    def _preempt_experiments(self):
        """Clear the GPU for user work: cancel every in-flight background
        experiment the user has not shielded before a user launch is submitted.

        Experiments belong to the closed app, and opening it drops the batch the
        last absence left (see :func:`origenerator.experiments.background
        .cancel_experiments`) — but one whose dequeue ComfyUI refused survives
        that sweep and is adopted as a live job. A video experiment can hold the
        GPU for many minutes; without this the user's job silently queues after
        it and their progress bar never moves, indistinguishable from a hang.
        Each preempted experiment is dropped exactly as a hand-cancel would drop
        it: interrupted or dequeued, its abandoned row deleted.
        """
        for jobs in list(self._jobs.values()):
            for job in list(jobs):
                if job.source == GenerationSource.EXPERIMENT and not job.shielded:
                    logger.info(
                        "Preempting background experiment %s for user work", job.prompt_id
                    )
                    self.cancel_job(job.prompt_id)

    def _register(self, key, job, on_finished):
        """Track a re-roll job for a folder and wire its completion and failure."""
        self._jobs.setdefault(key, []).append(job)
        job.finished.connect(
            lambda files, thumb, dur, k=key, j=job: on_finished(k, j, files, thumb, dur)
        )
        job.failed.connect(lambda msg, k=key, j=job: self._on_failed(k, j, msg))
        job.preview.connect(
            lambda data, k=key, j=job: self.preview.emit(k, j.prompt_id, data)
        )
        # Persist the job's live progress onto its row so a restart mid-run can resume
        # the bar at its last position (see GenerationJob.reconnect(progress_state=…)).
        job.progress.connect(lambda *_, j=job: self._persist_progress(j))

    def _persist_progress(self, job: GenerationJob):
        """Write a running job's progress to its row, throttled to spare the disk."""
        now = time.monotonic()
        if now - self._progress_persist_at.get(job.prompt_id, 0.0) < _PROGRESS_PERSIST_INTERVAL_S:
            return
        self._progress_persist_at[job.prompt_id] = now
        try:
            self._db.update_generation(
                job.prompt_id, progress_json=json.dumps(job.progress_state())
            )
        except Exception as e:  # a persistence hiccup must never disrupt a live run
            logger.debug("Could not persist progress for %s: %s", job.prompt_id, e)

    def reconnect_running(self):
        """Pick a previous session's in-flight generations back up.

        Every still-in-flight row is taken back so its completion is recorded and
        its tile shows live progress again — even for a folder the user hasn't
        opened yet. A tab's Generate is itself a re-roll, so no in-flight row is
        owned elsewhere. Called once at startup.

        Two kinds, told apart by the row's status. A ``running`` row was handed to
        ComfyUI and is the server's to finish, so it is rebound live. A
        ``pending`` one never left this app — the line was still holding it when
        the app closed — so it rejoins the line, oldest first, and the queue's own
        rules put it back where it belongs. A held row whose workflow no longer
        exists can never be sent, so it is dropped rather than left in flight
        forever.
        """
        if self._client is None:
            return
        # Read the frame configs straight from the DB: the first tree rebuild
        # (which would populate the view's image rows) hasn't run yet at startup.
        index = self._image_config_index()
        # Oldest first, against the newest-first listing: the line is rebuilt by
        # re-queuing each job in the order it was asked for, so the rules that
        # ordered it the first time order it the same way again.
        for row in reversed(self._db.list_generations()):
            if row.get("status") == GenerationStatus.RUNNING:
                self._reconnect(row, index)
            elif row.get("status") == GenerationStatus.PENDING:
                self._readopt(row, index)
        self._pump()
        self.changed.emit()

    def _image_config_index(self) -> dict:
        """The frame-config index for keying image-conditioned folders, built from
        the current image rows so an i2v row keys to the same leaf the tree gives
        it (see :func:`gallery.build_image_config_index`)."""
        image_rows = [
            r for r in self._db.list_generations()
            if gallery.media_type_of_row(r) == MediaType.IMAGE
        ]
        return gallery.build_image_config_index(image_rows)

    def _reconnect(self, row: dict, image_index: dict):
        key = gallery.settings_folder_key(row, image_index)
        if self.job_for_prompt(row["prompt_id"]) is not None:
            return  # already tracked
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return
        params = gallery.parse_params(row.get("params_json"))
        try:
            # Carry the row's source onto the rebound job, so an experiment left
            # running by a previous session is still preemptible by user work.
            job = GenerationJob.reconnect(
                self._client, workflow, params, row["prompt_id"],
                progress_state=_parse_progress_state(row.get("progress_json")),
                source=source_of(row),
            )
        except Exception as e:
            logger.warning("Could not reconnect re-roll for %s: %s", key, e)
            return
        self._take_back(key, job, row)
        self._on_server.append(job)  # it is ComfyUI's to finish, not ours to send

    def _readopt(self, row: dict, image_index: dict):
        """Take a row the line was still holding back into the line.

        Nothing of it is running on the server, so there is nothing to rebind
        to and nothing lost by rebuilding it: the job comes back under the row's
        own prompt id and waits its turn like any other — asking, when the turn
        comes, after any run of it the line had set aside
        (:meth:`GenerationJob.readopt`). One whose workflow the app no longer
        has is deleted instead — it could never be sent, and left alone it
        would sit in the queue forever.
        """
        key = gallery.settings_folder_key(row, image_index)
        if self.job_for_prompt(row["prompt_id"]) is not None:
            return  # already tracked
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        try:
            if workflow is None:
                raise ValueError(f"unknown workflow {row.get('workflow_name')!r}")
            job = GenerationJob.readopt(
                self._client, workflow, gallery.parse_params(row.get("params_json")),
                row["prompt_id"], source=source_of(row),
            )
        except Exception as e:
            logger.warning("Dropping a queued generation we can no longer build: %s", e)
            self._db.delete_generation(row["prompt_id"])
            return
        self._take_back(key, job, row)
        self._enqueue(job)

    def _take_back(self, key: str, job: GenerationJob, row: dict):
        job.origin = job.prompt_id  # a resumed run's chain, if any, is already done
        job.shielded = bool(row.get("shielded"))
        self._register(key, job, self._on_finished)

    @property
    def queue_order(self) -> list[str]:
        """Prompt ids in the order they will run: what ComfyUI holds, the run it
        is making first, then the line.

        Whatever displays the queue orders itself by this rather than by when the
        rows were made — the rules that put an image in front of a video leave no
        mark on anything the database records.
        """
        making_first = sorted(self._on_server, key=lambda job: job.state != JobState.RUNNING)
        return [job.prompt_id for job in making_first + self._waiting]

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

    def reorder(self, prompt_ids: list[str]):
        """Rearrange the waiting line into ``prompt_ids`` order, after what is
        put first.

        A drag in the queue strip, and it costs nothing: a waiting job has never
        been sent, so its place is ours to change. Ids this app holds no waiting
        job for are ignored — another app's prompts, a finished one, and the job
        already on the server, which has no place in front of it to be moved to.
        Any waiting job the list doesn't name keeps its place at the back.
        """
        place = {pid: index for index, pid in enumerate(prompt_ids)}
        self._waiting.sort(key=lambda job: place.get(job.prompt_id, len(place)))
        queue_line.put_first(self._waiting, self._first)

    def cancel(self, key: str):
        """Stop and forget the job leading a folder's queue, dropping its row.

        The folder-level stop — the live tile's Cancel. A folder with more than one
        job queued gives up the one in front; the rest are stopped from the queue
        strip, a row at a time (:meth:`cancel_job`).

        Silent — no :attr:`changed` emit: the tile's cancel button drives its own
        follow-up redraw.
        """
        job = self.job_for(key)
        if job is not None:
            self.cancel_job(job.prompt_id)

    def cancel_job(self, prompt_id: str):
        """Stop and forget one named job, dropping its abandoned running row.

        What a queue row's Cancel calls, and how an experiment is preempted: a
        folder may hold several jobs, so the one to stop has to be named rather
        than inferred from its folder.
        """
        for key, jobs in list(self._jobs.items()):
            for job in list(jobs):
                if job.prompt_id == prompt_id:
                    self._drop(key, job)
                    job.cancel()
                    record_unfinished_run(self._db, job, SeedUseKind.CANCELED)
                    self._db.delete_generation(prompt_id)  # drop the abandoned row
                    self._pump()  # the machine is free: start whatever is next
                    return

    def _on_image_finished(self, key, image_job, files, thumb_path, duration,
                           video_workflow, video_params):
        """First stage of a chained i2v re-roll: finalize the fresh image, then run
        the video on it, pointing its input at the just-saved output. The video
        stage inherits the run's origin, so whoever launched it still sees one run."""
        self._drop(key, image_job)
        mark_generation_completed(self._db, image_job.prompt_id, files, thumb_path, duration)
        input_ref = gallery.output_file_reference(files)
        if input_ref is not None:
            video_params = {**video_params, "input_image": input_ref}
        self._launch(key, video_workflow, video_params, self._on_finished,
                     origin=image_job.origin, shielded=image_job.shielded)
        self._pump()  # in case the video stage couldn't even be built

    def _on_finished(self, key, job, files, thumb_path, duration):
        self._drop(key, job)
        self._pump()  # the machine is free: start whatever is next
        mark_generation_completed(self._db, job.prompt_id, files, thumb_path, duration)
        outcome = _outcome_of(self._db, job, ok=True, seconds=duration)
        self.finished.emit(key, job.prompt_id, job.origin)
        self.run_ended.emit(outcome)

    def _on_failed(self, key, job, message):
        self._drop(key, job)
        self._pump()  # the machine is free: start whatever is next
        record_unfinished_run(self._db, job, SeedUseKind.FAILED)
        self._db.update_generation(job.prompt_id, status=GenerationStatus.ERROR,
                                   error_message=message)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self.failed.emit(key, message)
        self.run_ended.emit(_outcome_of(self._db, job, ok=False))
