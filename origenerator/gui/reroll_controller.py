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
actions (:meth:`start`, :meth:`cancel`) let their sole caller drive the follow-up
UI directly; the signals carry the events that arrive asynchronously from a job.
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
        self._jobs: dict[str, GenerationJob] = {}  # settings-folder key -> job
        self._progress_persist_at: dict[str, float] = {}  # prompt_id -> last-write time

    @property
    def jobs(self) -> dict:
        """The live re-roll jobs, keyed by settings-folder key (read-only view)."""
        return self._jobs

    def job_for(self, key: str):
        """The live re-roll job for a folder, or ``None``."""
        return self._jobs.get(key)

    def has(self, key: str) -> bool:
        return key in self._jobs

    def _launchable(self, key: str, source: str = "generated") -> bool:
        """Whether a launch may claim ``key``. An idle folder always may. A
        folder whose live job is a background experiment may be claimed by user
        work — :meth:`_launch` preempts the experiment — but never by another
        experiment, and a folder running user work is claimed by no one."""
        job = self._jobs.get(key)
        if job is None:
            return True
        return source != "experiment" and job.source == "experiment"

    def start_prepared(self, key: str, workflow, params: dict, *,
                       source: str = "generated") -> bool:
        """Launch a job with already-built ``params`` under folder ``key``.

        Unlike :meth:`start`, the caller owns the params — no defaults are filled
        and no seed is re-rolled. This is the gallery's image+video combine (which
        reuses the recipe video's exact seed) and the background experimenter,
        which tags its rows with ``source="experiment"``. Returns ``True`` once
        the job is tracked; ``False`` when there's no client, a job for ``key`` is
        already running, or the submit failed (``_launch`` drops the job then).
        """
        if self._client is None or not self._launchable(key, source):
            return False
        self._launch(key, workflow, params, self._on_finished, source=source)
        return key in self._jobs

    def start_reroll_from_image(self, key: str, image_row: dict, image_workflow,
                                video_workflow, video_params: dict) -> bool:
        """Re-roll a fresh start frame from ``image_row`` (a new image seed), then
        run ``video_workflow`` with the already-built ``video_params`` on it.

        The gallery combine's image-seed and both-seed choices: the frame to re-roll
        is the dropped image itself, so — unlike :meth:`reroll_image_seed` — the
        image row is handed in directly rather than looked up from a video's input.
        The caller owns ``video_params`` (already seed-kept or re-rolled to taste).
        Returns ``True`` once the chained job is tracked; ``False`` with no client
        or a job for ``key`` already running.
        """
        if self._client is None or not self._launchable(key):
            return False
        self._launch(
            key, image_workflow, prepared_params(image_row, image_workflow),
            lambda k, job, files, thumb, dur: self._on_image_finished(
                k, job, files, thumb, dur, video_workflow, video_params
            ),
        )
        return key in self._jobs

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

    def _launch(self, key, workflow, params, on_finished, *, source="generated"):
        """Build, register and submit one re-roll job, wiring its completion to
        ``on_finished(key, job, files, thumb_path, duration)``.

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
        self._register(key, job, on_finished)
        insert_generation_row(self._db, job)
        try:
            job.start()
            self._db.update_generation(job.prompt_id, status="running")
        except Exception as e:
            logger.warning("Re-roll submission failed for %s: %s", key, e)
            self._db.update_generation(job.prompt_id, status="error", error_message=str(e))
            self._jobs.pop(key, None)
        self.changed.emit()

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
        for key, job in list(self._jobs.items()):
            if job.source == "experiment":
                logger.info(
                    "Preempting background experiment %s for user work", job.prompt_id
                )
                self.cancel(key)

    def _register(self, key, job, on_finished):
        """Track a re-roll job for a folder and wire its completion and failure."""
        self._jobs[key] = job
        job.finished.connect(
            lambda files, thumb, dur, k=key, j=job: on_finished(k, j, files, thumb, dur)
        )
        job.failed.connect(lambda msg, k=key: self._on_failed(k, msg))
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
        if key in self._jobs:
            return  # a job for this folder is already tracked
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
        self._register(key, job, self._on_finished)

    def cancel(self, key: str):
        """Stop and forget a folder's running re-roll, dropping its abandoned row.

        Silent — no :attr:`changed` emit: the tile's cancel button drives its own
        follow-up redraw, and the other caller (:meth:`_preempt_experiments`) is
        immediately followed by a launch that emits it anyway.
        """
        job = self._jobs.pop(key, None)
        if job is not None:
            job.cancel()
            self._db.delete_generation(job.prompt_id)  # drop the abandoned running row

    def _on_image_finished(self, key, image_job, files, thumb_path, duration,
                           video_workflow, video_params):
        """First stage of a chained i2v re-roll: finalize the fresh image, then run
        the video on it, pointing its input at the just-saved output."""
        self._jobs.pop(key, None)
        mark_generation_completed(self._db, image_job.prompt_id, files, thumb_path, duration)
        input_ref = gallery.output_file_reference(files)
        if input_ref is not None:
            video_params = {**video_params, "input_image": input_ref}
        self._launch(key, video_workflow, video_params, self._on_finished)

    def _on_finished(self, key, job, files, thumb_path, duration):
        self._jobs.pop(key, None)
        mark_generation_completed(self._db, job.prompt_id, files, thumb_path, duration)
        self.finished.emit(key, job.prompt_id)

    def _on_failed(self, key, message):
        job = self._jobs.pop(key, None)
        if job is not None:
            self._db.update_generation(job.prompt_id, status="error", error_message=message)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self.failed.emit(key)
