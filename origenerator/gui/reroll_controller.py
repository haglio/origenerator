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

import logging

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import gallery
from origenerator.generation_config import prepared_params
from origenerator.gui.generation_job import (
    GenerationJob, insert_generation_row, mark_generation_completed,
)
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


class RerollController(QObject):
    """Tracks one in-flight job (re-roll or combine) per settings-folder key and
    drives each to completion, emitting the redraws the view should make along
    the way."""

    changed = pyqtSignal()            # the set of live re-rolls changed (add/reconnect)
    preview = pyqtSignal(str, bytes)  # (folder key, frame) a job streamed a frame
    finished = pyqtSignal(str)        # (folder key) a re-roll finished and was saved
    failed = pyqtSignal(str)          # (folder key) a re-roll failed

    def __init__(self, db, client, parent=None):
        super().__init__(parent)
        self._db = db
        self._client = client
        self._jobs: dict[str, GenerationJob] = {}  # settings-folder key -> job

    @property
    def jobs(self) -> dict:
        """The live re-roll jobs, keyed by settings-folder key (read-only view)."""
        return self._jobs

    def job_for(self, key: str):
        """The live re-roll job for a folder, or ``None``."""
        return self._jobs.get(key)

    def has(self, key: str) -> bool:
        return key in self._jobs

    def start_prepared(self, key: str, workflow, params: dict) -> bool:
        """Launch a job with already-built ``params`` under folder ``key``.

        Unlike :meth:`start`, the caller owns the params — no defaults are filled
        and no seed is re-rolled. This is the gallery's image+video combine, which
        reuses the recipe video's exact seed. Returns ``True`` once the job is
        tracked; ``False`` when there's no client, a job for ``key`` is already
        running, or the submit failed (``_launch`` drops the job in that case).
        """
        if self._client is None or key in self._jobs:
            return False
        self._launch(key, workflow, params, self._on_finished)
        return key in self._jobs

    def start(self, key: str, group, image_rows: list[dict]):
        """Launch a fresh variation of the settings folder ``key`` names.

        An i2v whose input image is itself a re-buildable generation re-rolls that
        image first (fresh start frame), then runs the video on it; any other row
        just re-rolls its one workflow with the same input, as before. A no-op when
        there's no client, the folder already has a running re-roll, or ``group``
        isn't a settings leaf with rows.
        """
        if self._client is None or key in self._jobs:
            return  # no client, or this folder already has one running
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        row = group.rows[0]
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return
        params = prepared_params(row, workflow)
        source = self._reroll_source_image(row, image_rows)
        if source is None:
            self._launch(key, workflow, params, self._on_finished)
        else:
            source_row, image_workflow = source
            image_params = prepared_params(source_row, image_workflow)
            self._launch(
                key, image_workflow, image_params,
                lambda k, job, files, thumb, dur: self._on_image_finished(
                    k, job, files, thumb, dur, workflow, params
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

    def _launch(self, key, workflow, params, on_finished):
        """Build, register and submit one re-roll job, wiring its completion to
        ``on_finished(key, job, files, thumb_path, duration)``.

        A running row is recorded before the job is submitted so an app restart
        mid-generation can find it and reconnect, exactly as the Generate tab does.
        """
        try:
            job = GenerationJob(self._client, workflow, params)
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

    def _register(self, key, job, on_finished):
        """Track a re-roll job for a folder and wire its completion and failure."""
        self._jobs[key] = job
        job.finished.connect(
            lambda files, thumb, dur, k=key, j=job: on_finished(k, j, files, thumb, dur)
        )
        job.failed.connect(lambda msg, k=key: self._on_failed(k, msg))
        job.preview.connect(lambda data, k=key: self.preview.emit(k, data))

    def reconnect_running(self, claimed_ids: set):
        """Rebind live jobs to any re-rolls left running by a previous session.

        Each still-in-flight row this app doesn't already own (a Generate tab owns
        its own jobs) is picked back up so its completion is recorded and its tile
        shows live progress again — even for a folder the user hasn't opened yet.
        Called once at startup, after the Generate tabs have claimed their jobs.
        """
        if self._client is None:
            return
        # Read the frame configs straight from the DB: the first tree rebuild
        # (which would populate the view's image rows) hasn't run yet at startup.
        index = self._image_config_index()
        for row in self._db.list_generations():
            if row.get("status") in ("running", "pending") and row["prompt_id"] not in claimed_ids:
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
            job = GenerationJob.reconnect(self._client, workflow, params, row["prompt_id"])
        except Exception as e:
            logger.warning("Could not reconnect re-roll for %s: %s", key, e)
            return
        self._register(key, job, self._on_finished)

    def cancel(self, key: str):
        """Stop and forget a folder's running re-roll, dropping its abandoned row.

        Silent: the tile's cancel button is the only caller, so the view drives the
        follow-up redraw itself rather than through :attr:`changed`.
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
        self.finished.emit(key)

    def _on_failed(self, key, message):
        job = self._jobs.pop(key, None)
        if job is not None:
            self._db.update_generation(job.prompt_id, status="error", error_message=message)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self.failed.emit(key)
