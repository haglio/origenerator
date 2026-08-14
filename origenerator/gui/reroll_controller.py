"""Owns the gallery's in-flight generation jobs: launching a fresh variation of a
settings folder (re-roll) or a video from an arbitrary image + another video's
recipe (combine, via :meth:`start_prepared`), chaining an i2v's image->video
stages, reconnecting jobs a prior session left running, and finalizing or failing
each in the database. Both kinds are keyed by their settings-folder key, so a
combine reconnects and lands in its folder exactly as a re-roll does.

Pure job/database machinery with no widget knowledge — it reports what the view
must redraw through signals (``changed`` to re-render the open folder, ``preview``
to mirror a live frame, ``finished``/``failed`` for a job's outcome) so the
GalleryView owns all presentation while this owns the lifecycle. View-initiated
actions (:meth:`start`, :meth:`cancel`, :meth:`reorder`) let their sole caller
drive the follow-up UI directly; the signals carry the events that arrive
asynchronously from a job.

It also holds the order ComfyUI will work through its queue in
(:attr:`queue_order`, re-read by :meth:`refresh_queue_order` on each poll), since
that is what a display of the queue must sort by — a reorder moves jobs on the
server without touching anything the database records about them.
"""

import json
import logging
import time

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import gallery
from origenerator.generation_config import filled_params, prepared_params
from origenerator.gui.generation_job import (
    GenerationJob, insert_generation_row, mark_generation_completed,
)
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# How often a running job's live progress is written to its row. Throttled because
# progress ticks fire per sampler step (sub-second for images); the persisted value
# only needs to be recent enough that a restart resumes the bar near where it was.
_PROGRESS_PERSIST_INTERVAL_S = 1.0


def _first_difference(current: list, wanted: list) -> int:
    """The first index at which two orderings part company (their common length
    when one is simply a prefix of the other)."""
    for index, (now, then) in enumerate(zip(current, wanted)):
        if now != then:
            return index
    return min(len(current), len(wanted))


def _parse_progress_state(raw):
    """The persisted progress snapshot for a row, or ``None`` when absent/corrupt."""
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return state if isinstance(state, dict) else None


class RerollController(QObject):
    """Tracks one in-flight job (re-roll or combine) per settings-folder key and
    drives each to completion, emitting the redraws the view should make along
    the way.

    User work owns the GPU: launching any user job first cancels every in-flight
    background experiment (the one generator of jobs the user didn't ask for), so
    a Generate starts at once instead of queuing behind a long experiment run."""

    changed = pyqtSignal()            # the set of live re-rolls changed (add/reconnect)
    preview = pyqtSignal(str, bytes)  # (folder key, frame) a job streamed a frame
    # (folder key, prompt_id) a re-roll finished and was saved. The prompt_id
    # tells the view whose completion this is — a user re-roll gets loaded into
    # the front tab, a background experiment leaves the tabs alone.
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str)          # (folder key) a re-roll failed

    def __init__(self, db, client, parent=None):
        super().__init__(parent)
        self._db = db
        self._client = client
        self._jobs: dict[str, list[GenerationJob]] = {}  # folder key -> its live jobs
        self._progress_persist_at: dict[str, float] = {}  # prompt_id -> last-write time
        self._queue_order: list[str] = []  # prompt ids as ComfyUI last listed them

    @property
    def jobs(self) -> dict:
        """The folder-facing view: each folder's *leading* live job, by folder key.

        A folder can have several queued at once, but the things keyed by folder —
        its one live re-roll tile, the selection that follows it — show the one in
        front. Use :attr:`all_jobs` for everything actually in flight.
        """
        return {key: jobs[0] for key, jobs in self._jobs.items() if jobs}

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
        return jobs[0] if jobs else None

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

    def _launchable(self, key: str, source: str = "generated") -> bool:
        """Whether a launch may join ``key``.

        User work always may, even into a folder already generating: ComfyUI runs
        one prompt at a time and the bottom strip shows the line, so a second
        Generate of the same settings queues behind the first instead of being
        silently refused — which is what blocked two pictures of one recipe from
        being re-rolled together. A background experiment still takes only an idle
        folder, and never stacks; user work preempts one in :meth:`_launch`.
        """
        return source != "experiment" or not self._jobs.get(key)

    def start_prepared(self, key: str, workflow, params: dict, *,
                       source: str = "generated") -> bool:
        """Launch a job with already-built ``params`` under folder ``key``.

        Unlike :meth:`start`, the caller owns the params — no defaults are filled
        and no seed is re-rolled. This is the gallery's image+video combine (which
        reuses the recipe video's exact seed) and the background experimenter,
        which tags its rows with ``source="experiment"``. Returns ``True`` once
        the job is tracked; ``False`` when there's no client, an experiment already
        holds ``key``, or the submit failed (``_launch`` drops the job then).
        """
        if self._client is None or not self._launchable(key, source):
            return False
        self._launch(key, workflow, params, self._on_finished, source=source)
        return self.has(key)

    def start_reroll_from_image(self, key: str, image_row: dict, image_workflow,
                                video_workflow, video_params: dict) -> bool:
        """Re-roll a fresh start frame from ``image_row`` (a new image seed), then
        run ``video_workflow`` with the already-built ``video_params`` on it.

        The gallery combine's image-seed and both-seed choices: the frame to re-roll
        is the dropped image itself, so — unlike :meth:`reroll_image_seed` — the
        image row is handed in directly rather than looked up from a video's input.
        The caller owns ``video_params`` (already seed-kept or re-rolled to taste).
        Returns ``True`` once the chained job is tracked; ``False`` with no client.
        """
        if self._client is None or not self._launchable(key):
            return False
        self._launch(
            key, image_workflow, prepared_params(image_row, image_workflow),
            lambda k, job, files, thumb, dur: self._on_image_finished(
                k, job, files, thumb, dur, video_workflow, video_params
            ),
        )
        return self.has(key)

    def start(self, key: str, group, image_rows: list[dict]):
        """Launch a fresh variation of the settings folder ``key`` names — both
        seeds re-rolled (a new start frame *and* a new video seed).

        An i2v whose input image is itself a re-buildable generation re-rolls that
        image first (fresh start frame), then runs the video on it; any other row
        just re-rolls its one workflow with the same input, as before. A no-op when
        there's no client, the folder already has a running re-roll, or ``group``
        isn't a settings leaf with rows.
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
        the item. Also a no-op with no client or a folder already re-rolling.
        """
        if self._client is None or not self._launchable(key):
            return  # no client, or this folder already has one running
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return
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
            )

    def _reroll_source_image(self, row: dict, image_rows: list[dict]):
        """The image generation ``row``'s input image came from, paired with its
        workflow, when the app can rebuild it — so an i2v re-roll can regenerate a
        fresh start frame first. ``None`` when there's no reusable source image."""
        source_id = gallery.find_source_image_id(row, image_rows)
        if source_id is None:
            return None
        source = self._db.get_generation(source_id)
        workflow = WORKFLOW_REGISTRY.get(source.get("workflow_name") or "") if source else None
        return (source, workflow) if workflow is not None else None

    def _launch(self, key, workflow, params, on_finished, *, source="generated",
                origin=None):
        """Build, register and submit one re-roll job, wiring its completion to
        ``on_finished(key, job, files, thumb_path, duration)``.

        ``origin`` is the prompt id the run began under, carried across a chained
        i2v's image→video hand-off so both stages read as one run; a fresh launch
        is its own origin.

        User work preempts a background experiment here, at the one choke point
        every user path funnels through — so a Generate never sits behind an
        experiment's run (see :meth:`_preempt_experiments`). A running row is
        recorded before the job is submitted so an app restart mid-generation can
        find it and reconnect, exactly as the Generate tab does.
        """
        if source != "experiment":
            self._preempt_experiments()
        try:
            job = GenerationJob(self._client, workflow, params, source=source)
        except Exception as e:
            logger.warning("Could not build a re-roll for %s: %s", key, e)
            return
        job.origin = origin or job.prompt_id  # a chained stage keeps the first id
        self._register(key, job, on_finished)
        insert_generation_row(self._db, job)
        try:
            job.start()
            self._db.update_generation(job.prompt_id, status="running")
        except Exception as e:
            logger.warning("Re-roll submission failed for %s: %s", key, e)
            self._db.update_generation(job.prompt_id, status="error", error_message=str(e))
            self._drop(key, job)
        self.changed.emit()

    def _drop(self, key: str, job: GenerationJob):
        """Forget one job, and the folder's entry once its last one is gone."""
        jobs = self._jobs.get(key)
        if not jobs or job not in jobs:
            return
        jobs.remove(job)
        if not jobs:
            del self._jobs[key]

    def _preempt_experiments(self):
        """Clear the GPU for user work: cancel every in-flight background
        experiment before a user launch is submitted.

        Experiments belong to the closed app, and opening it drops the batch the
        last absence left (see :func:`origenerator.experiments.background
        .cancel_experiments`) — but one whose dequeue ComfyUI refused survives
        that sweep and is adopted as a live job. A video experiment can hold the
        GPU for many minutes; without this the user's job silently queues behind
        it and their progress bar never moves, indistinguishable from a hang.
        Each preempted experiment is dropped exactly as a hand-cancel would drop
        it: interrupted or dequeued, its abandoned row deleted.
        """
        for key, jobs in list(self._jobs.items()):
            for job in list(jobs):
                if job.source == "experiment":
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
        job.preview.connect(lambda data, k=key: self.preview.emit(k, data))
        # Persist the job's live progress onto its row so a restart mid-run can resume
        # the bar at its last position (see GenerationJob.reconnect(progress_state=…)).
        job.progress.connect(lambda value, mx, j=job: self._persist_progress(j))

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
        """Rebind live jobs to any re-rolls left running by a previous session.

        Every still-in-flight row is picked back up so its completion is recorded
        and its tile shows live progress again — even for a folder the user hasn't
        opened yet. A tab's Generate is itself a re-roll, so no in-flight row is
        owned elsewhere. Called once at startup.
        """
        if self._client is None:
            return
        # Read the frame configs straight from the DB: the first tree rebuild
        # (which would populate the view's image rows) hasn't run yet at startup.
        index = self._image_config_index()
        for row in self._db.list_generations():
            if row.get("status") in ("running", "pending"):
                self._reconnect(row, index)
        self.changed.emit()

    def _image_config_index(self) -> dict:
        """The frame-config index for keying image-conditioned folders, built from
        the current image rows so an i2v row keys to the same leaf the tree gives
        it (see :func:`gallery.build_image_config_index`)."""
        image_rows = [
            r for r in self._db.list_generations() if gallery.media_type_of_row(r) == "image"
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
                source=row.get("source") or "generated",
            )
        except Exception as e:
            logger.warning("Could not reconnect re-roll for %s: %s", key, e)
            return
        job.origin = job.prompt_id  # a resumed run's chain, if any, is behind it
        self._register(key, job, self._on_finished)

    @property
    def queue_order(self) -> list[str]:
        """Prompt ids in the order ComfyUI will run them, as of the last refresh.

        Whatever displays the queue orders itself by this rather than by when the
        rows were made: a reorder moves jobs in ComfyUI without touching anything
        the database records about them.
        """
        return self._queue_order

    def refresh_queue_order(self):
        """Re-read that order. A caller that polls invokes this each tick.

        A read that fails leaves the last known order standing — dropping to none
        would reshuffle the queue on screen every time ComfyUI hiccups, and the
        order it last gave is still the best answer available.
        """
        if self._client is None:
            return
        try:
            self._queue_order = self._client.queue_order()
        except Exception as e:
            logger.debug("Could not read the queue order: %s", e)

    def reorder(self, prompt_ids: list[str]):
        """Make ComfyUI work through this app's waiting jobs in ``prompt_ids`` order.

        A job moves by leaving the queue and rejoining the back of it (see
        :meth:`GenerationJob.requeue`), so only the jobs from the first position
        that differs onward are touched — requeuing one that hasn't moved would
        push it behind another app's work for nothing. Ids no live job here owns
        (another app's prompts, a finished one) and any job ComfyUI has already
        started are skipped: neither can be moved from here.

        A queue that can't be read leaves everything alone: "from where it first
        differs" has no answer without the order as it stands now, and a reshuffle
        on a guess is worse than none.
        """
        if self._client is None:
            return
        jobs = {job.prompt_id: job for job in self.all_jobs}
        movable = {pid for pid, job in jobs.items() if job.state == "queued"}
        wanted = [pid for pid in prompt_ids if pid in movable]
        try:
            current = [pid for pid in self._client.queue_order() if pid in movable]
        except Exception as e:
            logger.warning("Could not read the queue to reorder it: %s", e)
            return
        for pid in wanted[_first_difference(current, wanted):]:
            jobs[pid].requeue()

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
                    self._db.delete_generation(prompt_id)  # drop the abandoned row
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
                     origin=image_job.origin)

    def _on_finished(self, key, job, files, thumb_path, duration):
        self._drop(key, job)
        mark_generation_completed(self._db, job.prompt_id, files, thumb_path, duration)
        self.finished.emit(key, job.prompt_id)

    def _on_failed(self, key, job, message):
        self._drop(key, job)
        self._db.update_generation(job.prompt_id, status="error", error_message=message)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self.failed.emit(key)
