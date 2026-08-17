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

It also *is* the queue. ComfyUI is handed one prompt at a time and the rest of
the line waits here, in the order :mod:`origenerator.queue_line` decides — images
in front, videos at the back, and no video started at all while the slideshow is
playing. A job waiting its turn has never been sent, so it can be re-ordered,
gated or dropped for free; a job already on the server can only be interrupted,
which is why the line lives on this side of the wire. :attr:`queue_order` is what
that line looks like to whatever displays it.

A waiting job still gets its database row up front (status ``pending``, the same
row it will run under), so a queue held overnight is still there after a restart
— :meth:`reconnect_running` picks the sent ones back up and re-adopts the unsent
ones — and so the app closing can hand ComfyUI everything left
(:meth:`flush_to_server`) rather than take it to the grave.
"""

import json
import logging
import time

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import gallery, queue_line
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
    """Tracks the in-flight jobs (re-rolls and combines) of each settings-folder
    key and drives each to completion, emitting the redraws the view should make
    along the way.

    It is also the queue: a launched job joins a line kept here and is handed to
    ComfyUI only when the machine is free and the queue's rules say it may go
    (see :mod:`origenerator.queue_line`), which is what lets an image jump ahead
    of a video and a slideshow keep videos off the GPU entirely.

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
        # The queue proper: what ComfyUI is holding for us (one job, normally —
        # more only when a previous session left several), and the line waiting
        # to be handed over, in the order it will be.
        self._on_server: list[GenerationJob] = []
        self._waiting: list[GenerationJob] = []
        self._videos_held = False  # the slideshow's gate (see :meth:`hold_videos`)

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
        experiment's run (see :meth:`_preempt_experiments`). The job joins the
        line rather than the server: its row is written first (``pending``, the
        row it will run under) so a restart can find it either way, and
        :meth:`_pump` hands it over when its turn comes.
        """
        try:
            job = GenerationJob(self._client, workflow, params, source=source)
        except Exception as e:
            logger.warning("Could not build a re-roll for %s: %s", key, e)
            return
        job.origin = origin or job.prompt_id  # a chained stage keeps the first id
        self._register(key, job, on_finished)
        insert_generation_row(self._db, job)
        self._enqueue(job)
        # Preempted after this job is in the line, not before: dropping an
        # experiment frees the machine and starts whatever is at the front, and
        # the front has to be this job by then or the wait it was preempted for
        # is just handed to something else.
        if source != "experiment":
            self._preempt_experiments()
        self._pump()
        self.changed.emit()

    # --- the line: joining it, and being handed over ------------------------

    def _enqueue(self, job: GenerationJob):
        """Put a built job in the line, wherever the queue's rules place it."""
        self._waiting.insert(queue_line.insertion_index(self._waiting, job), job)

    def _pump(self):
        """Hand ComfyUI the next job it may start, if it isn't holding one of ours.

        One at a time: the whole reason the line is kept here is that a prompt
        already on the server can no longer be re-ordered or held back, so
        nothing is sent until the machine is free to run it. A submit that fails
        takes that job out of the line and the next one is tried, rather than the
        queue stalling on a job the server refuses.
        """
        while not self._on_server:
            job = queue_line.next_ready(self._waiting, videos_held=self._videos_held)
            if job is None:
                return  # nothing may start: an empty line, or only held videos
            self._waiting.remove(job)
            if self._hand_over(job):
                return

    def _hand_over(self, job: GenerationJob) -> bool:
        """Submit one job to ComfyUI, reporting whether the server took it."""
        key = self._key_of(job)
        try:
            job.start()
        except Exception as e:
            logger.warning("Re-roll submission failed for %s: %s", key, e)
            self._db.update_generation(job.prompt_id, status="error", error_message=str(e))
            self._drop(key, job)
            return False
        self._on_server.append(job)
        self._db.update_generation(job.prompt_id, status="running")
        return True

    def flush_to_server(self) -> int:
        """Hand ComfyUI everything still waiting, and say how much went.

        What the closing app calls. ComfyUI outlives Origenerator and works
        through its queue alone, so a line held back for the user's sake — the
        videos a slideshow was keeping off the GPU, the batch of experiments the
        close just queued — belongs to the server the moment there is no longer a
        user to hold it for. Every rule this queue has is about not interrupting
        somebody who is watching.
        """
        handed = 0
        for job in list(self._waiting):
            self._waiting.remove(job)
            if self._hand_over(job):
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
            if row.get("status") == "running":
                self._reconnect(row, index)
            elif row.get("status") == "pending":
                self._readopt(row, index)
        self._pump()
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
        self._on_server.append(job)  # it is ComfyUI's to finish, not ours to send

    def _readopt(self, row: dict, image_index: dict):
        """Take a row the line was still holding back into the line.

        It was never submitted, so there is nothing on the server to rebind to
        and nothing lost by rebuilding it: the job comes back unsent, under the
        row's own prompt id, and waits its turn like any other. One whose
        workflow the app no longer has is deleted instead — it could never be
        sent, and left alone it would sit in the queue forever.
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
                row["prompt_id"], source=row.get("source") or "generated",
            )
        except Exception as e:
            logger.warning("Dropping a queued generation we can no longer build: %s", e)
            self._db.delete_generation(row["prompt_id"])
            return
        job.origin = job.prompt_id
        self._register(key, job, self._on_finished)
        self._enqueue(job)

    @property
    def queue_order(self) -> list[str]:
        """Prompt ids in the order they will run: what ComfyUI holds, then the line.

        Whatever displays the queue orders itself by this rather than by when the
        rows were made — the rules that put an image in front of a video leave no
        mark on anything the database records.
        """
        return [job.prompt_id for job in self._on_server + self._waiting]

    @property
    def videos_held(self) -> bool:
        """Whether the slideshow's gate is currently keeping videos off the GPU."""
        return self._videos_held

    def held_jobs(self) -> list:
        """The waiting jobs the gate is holding — what a surface names as held."""
        return queue_line.held_back(self._waiting, videos_held=self._videos_held)

    def hold_videos(self, held: bool):
        """Keep videos off the GPU while a slideshow plays — or let them run again.

        A video generation saturates the card the show is being drawn with, and a
        show is exactly the stretch when nobody is waiting on a video. So while
        one plays, videos are passed over and images still go; when it closes,
        whatever the gate held starts at once.
        """
        if held == self._videos_held:
            return
        self._videos_held = held
        self._pump()
        self.changed.emit()

    def reorder(self, prompt_ids: list[str]):
        """Rearrange the waiting line into ``prompt_ids`` order.

        A drag in the queue strip, and it costs nothing: a waiting job has never
        been sent, so its place is ours to change. Ids this app holds no waiting
        job for are ignored — another app's prompts, a finished one, and the job
        already on the server, which has no place in front of it to be moved to.
        Any waiting job the list doesn't name keeps its place at the back.
        """
        place = {pid: index for index, pid in enumerate(prompt_ids)}
        self._waiting.sort(key=lambda job: place.get(job.prompt_id, len(place)))

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
                     origin=image_job.origin)
        self._pump()  # in case the video stage couldn't even be built

    def _on_finished(self, key, job, files, thumb_path, duration):
        self._drop(key, job)
        self._pump()  # the machine is free: start whatever is next
        mark_generation_completed(self._db, job.prompt_id, files, thumb_path, duration)
        self.finished.emit(key, job.prompt_id)

    def _on_failed(self, key, job, message):
        self._drop(key, job)
        self._pump()  # the machine is free: start whatever is next
        self._db.update_generation(job.prompt_id, status="error", error_message=message)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self.failed.emit(key)
