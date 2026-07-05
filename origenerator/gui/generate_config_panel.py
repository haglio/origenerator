import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter,
    QComboBox, QPushButton, QProgressBar, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator import evolver_export
from origenerator.comfyui_client import ComfyUIClient
from origenerator.completion import extract_completion
from origenerator.db import Database
from origenerator.gallery import (
    animated_preview_path, build_image_config_index, config_tab_title,
    find_source_image_id, media_type_of_row, output_file_reference,
    resolve_preview, rows_in_settings, settings_signature, source_image_id_for,
    videos_from_source_image, workflow_output_type,
)
from origenerator.generation_config import (
    ConfigSnapshot, find_duplicate_generation, merge_denormalized,
    prepared_params, randomize_seeds,
)
from origenerator.funscript import funscript_path_for, read_actions
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.generation_job import GenerationJob, persist_generation
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.param_form import ParamForm
from origenerator.gui.reroll_prompt import (
    REROLL_BOTH, REROLL_IMAGE, REROLL_VIDEO, offer_reroll,
)
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.thumbnail_strip import ThumbnailStrip
from origenerator.progress import ProgressTracker
from origenerator.timing import estimate_label, format_duration
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.config import (
    COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, EVOLVER_SOURCE, THUMB_DIR,
)

logger = logging.getLogger(__name__)

_ANIMATED_STRIP_LIMIT = 8  # most animation previews shown for one image at once


class GenerateConfigPanel(QWidget):
    """One generation configuration: pick a workflow, set params, run a job.

    Several panels share a single ComfyUIClient, so each filters the client's
    signals down to its own in-flight job. The panel lays out two resizable panes
    itself — a main column with the live preview over the settings and run
    controls, and this tab's own slim strip of past runs on the right. Clicking a
    strip thumbnail re-emits its prompt id via ``strip_activated`` so a container
    can open (or reuse) a tab for it.

    Below the run controls sits a footer that appears only while the tab is
    displaying a saved generation (:meth:`show_saved_generation`): for an image,
    the videos it was animated into; for a video, a link back to its source image;
    and a Send-to-Evolver button for a video. A blank tab, or one running a fresh
    job, hides all three.
    """

    title_changed = pyqtSignal(str)     # current tab title
    strip_activated = pyqtSignal(str)   # a strip thumbnail was clicked (prompt_id)
    source_activated = pyqtSignal(str)      # the "from source image" link (prompt_id)
    animated_activated = pyqtSignal(str)    # a footer animation tile (prompt_id)
    generate_requested = pyqtSignal(str, dict)  # Generate clicked: (workflow_name, form params)
    osr2_drive_toggled = pyqtSignal(bool)   # "Drive OSR2" turned on/off for the shown video

    def __init__(self, client: ComfyUIClient | None, db: Database, queue=None,
                 parent=None):
        super().__init__(parent)
        self._client = client                        # None in a read-only gallery: the form shows, but Generate is off
        self._db = db
        self._queue = queue                          # serializes jobs across panels; None = run at once
        self._client_prompt_id: str | None = None   # our uuid: the DB row key, and the id ComfyUI keys its signals on
        self._submitted_workflow = None              # workflow captured at submit time
        self._prepared: dict | None = None           # a job built but not yet started
        self._custom_title: str | None = None        # user-set name; overrides the auto title
        self._bar_state = "ready"                     # drives the progress bar's text + color
        self._executing = False                        # has ComfyUI started our prompt yet?
        self._progress_tracker: ProgressTracker | None = None  # folds multi-pass sampling into one ramp
        self._strip_ids: list[str] = []               # this tab's strip: seeded folder + its own runs, newest first
        self._param_form: ParamForm | None = None
        self._input_image_job: GenerationJob | None = None  # a random-input pre-step, before the main job
        self._last_frame: bytes | None = None         # latest live preview frame, for an external in-flight view
        self._last_progress: tuple[int, int] | None = None  # (cumulative, total) steps, for the running-job bar
        self._displayed_row: dict | None = None        # a saved generation this tab is showing (footer visible); None when blank/generating
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Two resizable panes, the divider doubling as a drag handle: a main column
        # (live preview on top, then the settings and run controls) and this tab's
        # own slim strip of past runs on the right.
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)

        # Main pane: the live preview over the settings form and run controls. The
        # preview leads (mirroring ComfyUI's frames, then the finished output); the
        # progress bar and buttons sit at the bottom, under the settings.
        main = QWidget()
        main_box = QVBoxLayout(main)
        main_box.setContentsMargins(0, 0, 0, 0)
        main_box.setSpacing(8)
        # The live preview leads the column: it mirrors ComfyUI's frames while a job
        # runs, shows the browsed generation's output when one is loaded, and the
        # newest matching result otherwise.
        self._preview = PreviewWidget()
        main_box.addWidget(self._preview, 3)
        header = QHBoxLayout()
        header.addWidget(QLabel("Workflow:"))
        self._workflow_combo = NoWheelComboBox()
        for key, wf in WORKFLOW_REGISTRY.items():
            self._workflow_combo.addItem(wf.display_name, key)
        self._workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)
        # Elide to a short floor when the window is narrow instead of holding the
        # width of the longest workflow name, which would set the tab's whole
        # minimum width and block tiling. It still expands to fill (stretch=1).
        self._workflow_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._workflow_combo.setMinimumContentsLength(12)
        header.addWidget(self._workflow_combo, 1)
        main_box.addLayout(header)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        main_box.addWidget(self._estimate_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        main_box.addWidget(self._scroll, 2)
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        main_box.addWidget(self._progress)
        self._show_ready()
        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setObjectName("generateBtn")
        self._generate_btn.clicked.connect(self._on_generate)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        btn_row.addStretch()
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._generate_btn)
        main_box.addLayout(btn_row)

        # Footer: shown only while this tab is displaying a saved generation (see
        # show_saved_generation). A "‹ From source image" link for a video whose
        # start frame is a known generation; the "Animated in" strip for an image;
        # Send-to-Evolver for a video. All hidden on a fresh tab.
        self._source_link = QLabel()
        self._source_link.setTextFormat(Qt.TextFormat.RichText)
        self._source_link.setOpenExternalLinks(False)
        self._source_link.linkActivated.connect(self.source_activated)
        self._source_link.hide()
        main_box.addWidget(self._source_link)

        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self.animated_activated)
        main_box.addWidget(self._animated_strip)

        self._evolver_btn = QPushButton("Send to Evolver")
        self._evolver_btn.setToolTip(
            "Copy this video into Evolver's inbox for sorting and upscaling."
        )
        self._evolver_btn.clicked.connect(self._on_send_to_evolver)
        self._evolver_btn.hide()  # shown only for a video the tab is displaying
        main_box.addWidget(self._evolver_btn)

        # Drive the OSR2 from this video's funscript, in sync with playback. Checkable
        # and shown only for a displayed video that has a funscript; toggling it is the
        # explicit opt-in that hands the device to (or releases it from) this tab.
        self._osr2_btn = QPushButton("Drive OSR2")
        self._osr2_btn.setCheckable(True)
        self._osr2_btn.setToolTip("Drive the OSR2 in sync with this video's funscript.")
        self._osr2_btn.toggled.connect(self._on_osr2_toggled)
        self._osr2_btn.hide()
        main_box.addWidget(self._osr2_btn)

        self._panes.addWidget(main)

        # Right pane: this tab's own accumulating strip of past runs, kept slim so
        # the whole window can still tile into a monitor third or a portrait half.
        self._strip = ThumbnailStrip(self._db)
        self._strip.thumbnail_activated.connect(self.strip_activated)
        self._panes.addWidget(self._strip)
        # The main column grows with the window; the strip holds its width. The
        # floor stays low enough that the window can still tile narrow.
        main.setMinimumWidth(230)
        self._panes.setStretchFactor(0, 1)
        self._panes.setStretchFactor(1, 0)
        self._panes.setSizes([500, 150])

        layout.addWidget(self._panes)

        if self._client is None:
            self._generate_btn.setEnabled(False)  # nothing to run against
        self._on_workflow_changed()

    def _connect_signals(self):
        if self._client is None:
            return  # a read-only gallery: no client signals to track
        self._client.progress.connect(self._on_progress)
        self._client.node_executing.connect(self._on_node_executing)
        self._client.preview_image.connect(self._on_preview)
        self._client.job_completed.connect(self._on_completed)
        self._client.job_error.connect(self._on_error)
        self._client.connected.connect(self._on_connected)
        self._client.disconnected.connect(self._on_disconnected)

    def teardown(self):
        """Disconnect from the shared client before the panel is destroyed."""
        if self._client is None:
            return  # never connected
        for signal, slot in (
            (self._client.progress, self._on_progress),
            (self._client.node_executing, self._on_node_executing),
            (self._client.preview_image, self._on_preview),
            (self._client.job_completed, self._on_completed),
            (self._client.job_error, self._on_error),
            (self._client.connected, self._on_connected),
            (self._client.disconnected, self._on_disconnected),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def _on_connected(self):
        if self._bar_state == "ready":  # don't clobber a job's status
            self._show_ready("Connected to ComfyUI")

    def _on_disconnected(self):
        if self._bar_state == "ready":
            self._show_ready("Disconnected")

    def _on_workflow_changed(self):
        key = self._workflow_combo.currentData()
        if key and key in WORKFLOW_REGISTRY:
            wf = WORKFLOW_REGISTRY[key]
            self._param_form = ParamForm(wf.param_definitions())
            self._param_form.changed.connect(self._emit_title)
            self._param_form.image_changed.connect(self._on_image_field_changed)
            self._scroll.setWidget(self._param_form)
        self._refresh_estimate()
        self._emit_title()
        self.show_recent_preview()  # these settings' newest result, not a blank pane

    def _emit_title(self):
        self.title_changed.emit(self.title())

    def _refresh_estimate(self):
        """Show how long this workflow typically takes, from its recent runs."""
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        durations = self._db.recent_durations(wf.name) if wf else []
        self._estimate_label.setText(f"Typical time: {estimate_label(durations)}")

    # --- progress bar: the panel's single status display -------------------
    # Text and color both live in the bar: grey while queued, blue (default)
    # while running, green when done, red on error. The barState property
    # drives the chunk color via the stylesheet.

    def _apply_bar_state(self, state: str):
        self._bar_state = state
        self._progress.setProperty("barState", state)
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)

    def _show_ready(self, text: str = "Ready"):
        self._apply_bar_state("ready")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat(text)

    def _show_waiting(self, text: str = "Queued…"):
        self._apply_bar_state("queued")
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setFormat(text)

    def _show_running(self):
        self._apply_bar_state("running")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("Generating… %p%")

    def _show_done(self, text: str):
        self._apply_bar_state("done")
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setFormat(text)

    def _show_error(self, text: str):
        self._apply_bar_state("error")
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setFormat(text)

    def _show_canceled(self, text: str = "Canceled"):
        self._apply_bar_state("canceled")
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setFormat(text)

    def _show_busy(self, text: str):
        """A running stage without step counts (the random-input pre-step): a
        live, moving bar rather than a stuck 0%."""
        self._apply_bar_state("running")
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setFormat(text)

    def _on_generate(self):
        """Ask the gallery to generate this config — a re-roll of its settings folder.

        A Generate is conceptually a gallery re-roll: it emits the form's workflow
        and values (a Random seed already re-rolled by :meth:`ParamForm.get_values`)
        as :attr:`generate_requested`, and the gallery launches the job in the
        folder's own re-roll slot and navigates there. The panel keeps only the
        form-level guard that an image workflow has its input picked.
        """
        if self._client is None:
            return  # a read-only gallery: nothing to run against
        key = self._workflow_combo.currentData()
        if not key or key not in WORKFLOW_REGISTRY:
            return
        wf = WORKFLOW_REGISTRY[key]
        params = self._param_form.get_values()

        missing_images = [
            pd.label for pd in wf.param_definitions()
            if pd.type == "image" and not str(params.get(pd.key, "")).strip()
        ]
        if missing_images:
            self._show_ready(
                f"Select an input image ({', '.join(missing_images)}) before generating."
            )
            return
        self.generate_requested.emit(key, params)

    def _generate(self, wf, params: dict, *, keep_preview: bool = False):
        """Submit ``wf`` with ``params`` as this tab's main job, warning first if
        a pinned seed would just re-create an identical past generation.

        ``keep_preview`` leaves the current preview frame up when the job starts
        (rather than clearing it) — used for the video stage of a random-input
        i2v, so its freshly generated input image stays on screen until the video
        streams a frame of its own.
        """
        snapshot = ConfigSnapshot(wf.name, params, self._param_form.seed_is_random())
        if find_duplicate_generation(self._db.list_generations(), snapshot):
            choice = self._offer_reroll(wf, params)
            if choice is None:
                return  # let the user change something rather than duplicate it
            if choice in (REROLL_VIDEO, REROLL_BOTH):
                params = randomize_seeds(params, wf.seed_keys())
                self._param_form.set_seed_random(True)
            if choice in (REROLL_IMAGE, REROLL_BOTH):
                # Draw a fresh start frame (new image seed) and run the video on
                # it, carrying whatever video seed we settled on just above.
                self._generate_random_input_then_run(wf, params)
                return

        # Build the job now (fixing the seed), but let the queue decide when it runs.
        prompt_id = str(uuid.uuid4())
        payload = wf.build_api_payload(params)
        self._prepare_job(
            payload=payload,
            workflow=wf,
            queue_name=wf.name,
            keep_preview=keep_preview,
            record=dict(
                prompt_id=prompt_id,
                workflow_name=wf.name,
                workflow_version=wf.version,
                positive_prompt=params.get("positive_prompt", ""),
                negative_prompt=params.get("negative_prompt", ""),
                seed=params.get("seed"),
                params_json=json.dumps(params),
                workflow_json=json.dumps(payload),
            ),
        )

    # --- random input image: a fresh source frame before the main job ---------

    def _generate_random_input_then_run(self, wf, params: dict):
        """Generate a fresh input image (the source image's settings, new seed),
        then run ``wf`` on it. Falls back to the current input if its source has
        since vanished (the Random box shouldn't have shown, but state can drift)."""
        source = self._input_image_source(params.get("input_image"))
        if source is None:
            self._generate(wf, params)
            return
        source_row, image_wf = source
        self._hide_footer()  # a fresh generation starts with the input pre-step
        job = GenerationJob(self._client, image_wf, prepared_params(source_row, image_wf))
        self._input_image_job = job
        job.preview.connect(self._note_frame)  # watch the frame take shape
        job.finished.connect(
            lambda files, thumb, dur, j=job: self._on_input_image_done(wf, params, j, files, thumb, dur)
        )
        job.failed.connect(self._on_input_image_failed)
        self._generate_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._show_busy("Generating input image…")
        try:
            job.start()
        except Exception as e:
            logger.error("Failed to submit input image: %s", e)
            self._on_input_image_failed(str(e))

    def _on_input_image_done(self, wf, params, job, files, thumb_path, duration):
        self._input_image_job = None
        persist_generation(self._db, job, files, thumb_path, duration)
        ref = output_file_reference(files)
        if ref is not None:
            params = {**params, "input_image": ref}
        # Keep the just-generated input image on screen until the video previews.
        self._generate(wf, params, keep_preview=True)

    def _on_input_image_failed(self, message: str):
        self._input_image_job = None
        self._show_error(f"Input image failed: {message[:100]}")
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    def _input_image_source(self, input_image):
        """The (image row, workflow) an ``input_image`` value was generated from,
        when the app can rebuild it; ``None`` for a hand-picked or unknown image."""
        source_id = source_image_id_for(input_image, self._image_rows())
        if source_id is None:
            return None
        row = self._db.get_generation(source_id)
        wf = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "") if row else None
        return (row, wf) if wf is not None else None

    def _image_rows(self):
        return [r for r in self._db.list_generations() if media_type_of_row(r) == "image"]

    def _on_image_field_changed(self, key: str, value: str):
        """Show the input's Random box only while it names a reproducible image."""
        self._param_form.set_image_random_available(
            key, self._input_image_source(value) is not None
        )

    def _offer_reroll(self, wf, params: dict) -> str | None:
        """Ask whether/how to re-roll a would-be duplicate (shared with the gallery).

        Offers the i2v two-seed choice only when the input image is itself a
        reproducible generation, so a fresh start frame can be drawn from it.
        """
        can_reroll_image = self._input_image_source(params.get("input_image")) is not None
        return offer_reroll(self, wf, can_reroll_image=can_reroll_image)

    def _prepare_job(self, *, payload: dict, workflow, queue_name: str, record: dict,
                     keep_preview: bool = False):
        """Stage a built job, then hand it to the queue (or run it now if unqueued).

        ``workflow`` is the WorkflowTemplate this job was built from, captured so
        its output node is used when the job completes. ``keep_preview`` rides
        along to :meth:`_begin_job` so a chained video stage doesn't wipe the
        input-image frame the queue may only start much later.
        """
        self._prepared = {"payload": payload, "workflow": workflow, "record": record,
                          "keep_preview": keep_preview}
        self._generate_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        if self._queue is not None:
            self._show_waiting()
            self._queue.submit(self, queue_name)
        else:
            self._begin_job()

    def run_now(self):
        """Start the prepared job — called by the queue when it reaches the head."""
        self._begin_job()

    def active_prompt_id(self) -> str | None:
        """The id of this panel's in-flight job, or ``None`` when idle.

        Set from submit until completion/error/cancel, so a container can persist
        it and reconnect the panel to a job still running after a restart.
        """
        return self._client_prompt_id

    def in_flight_descriptor(self) -> dict | None:
        """This panel's in-flight job as a plain descriptor for an external
        in-flight view (the gallery's Recents shelf), or ``None`` when idle.

        Covers every in-flight stage: a job actively executing, one still waiting
        its turn in the local queue (staged but not begun), and the random-input
        pre-step that runs before the main job. ``frame`` is the latest live
        preview, if one has arrived. A container pairs this with a way to reveal
        the panel, so a click on the card brings this tab forward.
        """
        if self._input_image_job is not None:
            prompt_id, status = self._input_image_job.prompt_id, "running"
        elif self._client_prompt_id is not None:
            prompt_id = self._client_prompt_id
            status = "running" if self._executing else "queued"
        elif self._prepared is not None:
            prompt_id, status = self._prepared["record"]["prompt_id"], "queued"
        else:
            return None
        return {
            "key": prompt_id,
            "caption": self.title(),
            "status": status,
            "frame": self._last_frame,
            "progress": self._last_progress,
            "media_type": workflow_output_type(self._workflow_combo.currentData()),
        }

    def reconnect(self, prompt_id: str, workflow, payload: dict):
        """Rebind to a job already running in ComfyUI, submitted by a prior session.

        Restores just enough state — the id its signals carry, the workflow that
        reads its output, and a progress ramp sized to its payload — for the
        panel's existing handlers to resume tracking it to completion. It never
        re-submits; the job is already on the server.
        """
        self._client_prompt_id = prompt_id
        self._submitted_workflow = workflow
        self._progress_tracker = ProgressTracker.for_payload(payload)
        self._executing = False
        self._generate_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._show_waiting("Reconnecting…")

    def _begin_job(self):
        job = self._prepared
        if job is None:
            return
        self._prepared = None
        self._hide_footer()  # a fresh generation: no longer showing a saved one
        record = job["record"]
        prompt_id = record["prompt_id"]
        self._db.insert_generation(**record)
        # Size the ramp to this run's total sampler steps so a multi-pass video
        # job fills once from 0 to 100 rather than resetting between passes.
        self._progress_tracker = ProgressTracker.for_payload(job["payload"])

        try:
            self._client.submit_job(job["payload"], prompt_id)
            self._client_prompt_id = prompt_id
            self._submitted_workflow = job["workflow"]
            self._db.update_generation(prompt_id, status="running")
            if not job["keep_preview"]:
                self._preview.clear()  # a fresh job: drop the previous result
            # else: a chained video stage — keep the input-image frame until it previews
            # The job is submitted but ComfyUI may be busy (even with work from
            # outside Origenerator), so it can sit in the server queue before it
            # starts. Show that wait instead of a stuck "Generating… 0%"; the bar
            # flips to running once ComfyUI actually begins our prompt.
            self._show_waiting("Queued on ComfyUI…")
        except Exception as e:
            logger.error("Failed to submit job: %s", e)
            self._db.update_generation(prompt_id, status="error", error_message=str(e))
            self._show_error(f"Error: {e}")
            self._generate_btn.setEnabled(True)
            self._cancel_btn.setEnabled(False)
            self._release_queue_slot()

    def set_queue_status(self, position: int, eta_seconds: float):
        """Show this panel's place in line and a countdown to its turn."""
        text = f"Queued (#{position})"
        if eta_seconds and eta_seconds > 0:
            text += f" — starts in ~{format_duration(eta_seconds)}"
        self._show_waiting(text)

    def _release_queue_slot(self):
        if self._queue is not None:
            self._queue.release(self)

    def _is_mine(self, prompt_id: str) -> bool:
        """True if a client signal's prompt_id belongs to this panel's job.

        The client multiplexes every panel's jobs over one connection, so each
        panel ignores signals for ids that aren't its own in-flight job.
        """
        return self._client_prompt_id is not None and prompt_id == self._client_prompt_id

    def _mark_running(self):
        """React to the first sign ComfyUI is actually working our prompt.

        Any of executing / progress / preview means our prompt has left the
        server queue and started, so (once) flip the bar from "Queued on
        ComfyUI…" to the running state and record that Cancel must now interrupt
        the run rather than merely dequeue it.
        """
        if not self._executing:
            self._executing = True
            self._show_running()

    def _on_progress(self, prompt_id: str, value: int, max_val: int):
        if not self._is_mine(prompt_id):
            return
        self._mark_running()
        if max_val > 0 and self._progress_tracker is not None:
            cumulative, total = self._progress_tracker.update(value, max_val)
            self._progress.setRange(0, total)
            self._progress.setValue(cumulative)
            self._last_progress = (cumulative, total)  # mirrored to the running-job bar

    def _on_node_executing(self, prompt_id: str, _node_id: str):
        # ComfyUI has begun running our prompt (vs. it merely sitting in the
        # server queue, behind e.g. a gallery re-roll or work from outside
        # Origenerator). ``executing`` precedes any ``progress`` for the prompt,
        # so it's the earliest signal that our turn has come.
        if self._is_mine(prompt_id):
            self._mark_running()

    def _on_preview(self, prompt_id: str, data: bytes):
        if self._is_mine(prompt_id):
            self._mark_running()
            self._note_frame(data)

    def _note_frame(self, data: bytes):
        """Remember the latest live preview frame — shown in this panel's preview
        and mirrored into any external in-flight view (the gallery's Recents shelf,
        which pulls it via :meth:`in_flight_descriptor`) — and display it here."""
        self._last_frame = data
        self._preview.show_frame(data)

    def _on_completed(self, prompt_id: str, history_data: dict):
        if not self._is_mine(prompt_id):
            return
        wf = self._submitted_workflow
        if not wf:
            return
        files, thumb_path, duration = extract_completion(
            wf, history_data, COMFYUI_OUTPUT_DIR, THUMB_DIR, self._client_prompt_id
        )
        if files:
            source = COMFYUI_OUTPUT_DIR / files[0].get("subfolder", "") / files[0]["filename"]
            if source.exists():
                self._preview.show_media(source, wf.output_type)

        fields = dict(
            status="completed",
            output_files=json.dumps(files),
            thumbnail_path=thumb_path,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        if duration is not None:
            fields["duration_seconds"] = duration
        self._db.update_generation(self._client_prompt_id, **fields)
        if duration is not None:
            self._show_done(f"Done in {format_duration(duration)}")
        else:
            self._show_done("Done!")
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        completed_id = self._client_prompt_id
        if completed_id not in self._strip_ids:
            self._strip_ids.insert(0, completed_id)  # accumulate; never drops earlier runs
            self._strip.show_generations(self._strip_ids)
        # The finished output is now what the tab is showing, so the footer (source
        # link / animations / Evolver) applies to it — re-read the row for the
        # freshly persisted output files it keys off.
        self._displayed_row = self._db.get_generation(completed_id)
        self._reset_job()
        self._refresh_estimate()
        self._release_queue_slot()

    def _on_error(self, prompt_id: str, error_msg: str):
        if not self._is_mine(prompt_id):
            return
        self._db.update_generation(
            self._client_prompt_id,
            status="error",
            error_message=error_msg,
        )
        self._show_error(f"Error: {error_msg[:100]}")
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._reset_job()
        self._release_queue_slot()

    def _on_cancel(self):
        """Stop this tab's generation: a queued slot, a server-queued prompt, or
        a running one — whichever stage it's at — leaving no half-done row."""
        if self._input_image_job is not None:  # still on the random-input pre-step
            self._input_image_job.cancel()
            self._input_image_job = None
            self._generate_btn.setEnabled(True)
            self._cancel_btn.setEnabled(False)
            self._show_canceled()
            return
        staged = self._prepared is not None
        prompt_id = self._client_prompt_id
        if self._queue is not None and (staged or prompt_id is not None):
            self._queue.cancel(self)  # drop our slot (pending or the running head)
        if prompt_id is not None:
            try:
                if self._executing:
                    self._client.interrupt()
                else:
                    self._client.cancel_prompt(prompt_id)
            except Exception as e:
                logger.warning("Cancel failed for %s: %s", prompt_id, e)
            self._db.delete_generation(prompt_id)
        elif not staged:
            return  # nothing in flight to cancel
        self._prepared = None
        self._reset_job()
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._show_canceled()

    def _reset_job(self):
        self._client_prompt_id = None
        self._submitted_workflow = None
        self._executing = False
        self._progress_tracker = None
        self._last_frame = None
        self._last_progress = None

    def settings_key(self) -> tuple[str, str] | None:
        """The gallery settings-folder this config maps to: (workflow, signature).

        The signature is normalized against the workflow's defaults (see
        ``canonical_settings``), so it matches the folder this tab's outputs land
        in and groups reruns that differ only by per-instance keys.
        ``None`` when no workflow is selected.
        """
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        if wf is None or self._param_form is None:
            return None
        params = self._param_form.get_values_static()
        index = build_image_config_index(self._image_rows())
        return key, settings_signature(key, json.dumps(params), index)

    def show_recent_preview(self):
        """When idle, fill the preview with the newest saved generation matching
        this tab's settings instead of the empty 'select a generation' placeholder
        — the most recent image/video generated with it. A no-op while a job of
        this tab's owns the preview."""
        if (self._client_prompt_id is not None or self._prepared is not None
                or self._input_image_job is not None):
            return  # a job of this tab's is driving the preview
        row = self._recent_matching_row()
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR) if row is not None else None
        if preview is not None:
            self._preview.show_media(*preview)
        else:
            self._preview.clear()  # nothing generated with these settings yet

    def _recent_matching_row(self) -> dict | None:
        """The newest saved generation in this tab's settings folder, or None."""
        rows = self._db.list_generations()  # newest first
        index = build_image_config_index([r for r in rows if media_type_of_row(r) == "image"])
        matching = rows_in_settings(rows, self.settings_key(), index)
        return matching[0] if matching else None

    def seed_strip(self, prompt_ids):
        """Seed this tab's strip with a settings folder when it opens from one.

        An accumulating history: whatever folder the tab was seeded with plus
        every generation it produces after — including runs whose settings no
        longer match the current form, so tweak-and-regenerate stays visible.
        """
        self._strip_ids = list(prompt_ids)
        self._strip.show_generations(self._strip_ids)

    def current_config(self) -> ConfigSnapshot:
        """Snapshot the live settings for comparison (without randomizing the seed)."""
        if self._param_form is None:
            return ConfigSnapshot(self._workflow_combo.currentData(), {}, False)
        return ConfigSnapshot(
            self._workflow_combo.currentData(),
            self._param_form.get_values_static(),
            self._param_form.seed_is_random(),
            self._param_form.image_is_random(),
        )

    def title(self) -> str:
        """The tab title: the user's custom name, else the model + gallery folder."""
        if self._custom_title:
            return self._custom_title
        params = self._param_form.get_values_static() if self._param_form else {}
        return config_tab_title(self._workflow_combo.currentData(), params)

    def set_custom_title(self, name: str):
        """Pin a user-chosen tab name that overrides the auto gallery-folder name."""
        self._custom_title = name
        self._emit_title()

    def custom_title(self) -> str | None:
        """The user-set tab name, or ``None`` when the title is auto-derived.

        Distinct from :meth:`title`, which always returns a displayable string;
        this reports only an explicit rename, for session persistence.
        """
        return self._custom_title

    def prefill(self, workflow_name: str, params: dict):
        # Switch to the matching workflow if found
        for i in range(self._workflow_combo.count()):
            if self._workflow_combo.itemData(i) == workflow_name:
                self._workflow_combo.setCurrentIndex(i)
                break
        if self._param_form:
            self._param_form.set_values(params)
        # Now that the settings match a real folder, show its newest result (the
        # workflow may not have changed above, so this doesn't ride on that signal).
        self.show_recent_preview()

    def restore_config(self, snapshot: ConfigSnapshot):
        """Reapply a snapshot captured by :meth:`current_config`.

        Like :meth:`prefill`, but also restores the seed's and the input image's
        Random states so a tab comes back the way it was left instead of pinned to
        the stale values that were in its fields at save time. The image box is set
        after prefill, once prefill's input value has told the panel whether that
        box should be available at all.
        """
        self.prefill(snapshot.workflow_name, snapshot.params)
        if self._param_form:
            self._param_form.set_seed_random(snapshot.seed_is_random)
            self._param_form.set_image_random(snapshot.image_is_random)

    # --- displaying a saved generation (the browsed selection) ----------------

    def show_saved_generation(self, row: dict, image_rows: list[dict]):
        """Display a browsed generation in this tab: seed the editable form with
        its settings, show its output in the preview, and reveal the footer for
        its media type (an image's animations, a video's source link + Evolver).

        The form is seeded first so its recent-preview autoshow doesn't override
        the selection's own output. A workflow the app can't rebuild leaves the
        form as it was but still shows the preview and footer.
        """
        self._displayed_row = row
        workflow_name = row.get("workflow_name", "")
        if workflow_name in WORKFLOW_REGISTRY:
            self.prefill(workflow_name, merge_denormalized(row))
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None:
            self._preview.show_media(*preview)  # after prefill, so it wins over autoshow
        else:
            self._preview.clear()
        self._show_footer(row, image_rows, preview)

    def _show_footer(self, row: dict, image_rows: list[dict], preview):
        """Populate and reveal the footer for the generation on display: the
        animations strip for an image, and the source link + Evolver button for a
        video. ``preview`` is the already-resolved ``(path, media_type)`` (or
        ``None``), so the Evolver button keys off the same on-disk lookup."""
        self._animated_strip.show_videos(self._animated_items(row))  # hides itself when empty
        source_id = find_source_image_id(row, image_rows)
        if source_id is not None:
            self._source_link.setText(f'<a href="{source_id}">‹ From source image</a>')
            self._source_link.show()
        else:
            self._source_link.hide()
        self._update_evolver_button(preview)
        self._update_osr2_button(preview)

    def _hide_footer(self):
        """Drop the saved-generation footer — a blank or generating tab shows none."""
        self._displayed_row = None
        self._animated_strip.show_videos([])
        self._source_link.hide()
        self._evolver_btn.hide()
        if self._osr2_btn.isChecked():
            self._osr2_btn.setChecked(False)  # a fresh job ends any drive (emits off)
        self._osr2_btn.hide()

    def _animated_items(self, row: dict) -> list[tuple]:
        """(prompt_id, looping-preview path, still path) for each video an image
        was animated into — empty for anything but an image with animations."""
        if media_type_of_row(row) != "image":
            return []
        videos = videos_from_source_image(row, self._video_rows())
        if len(videos) > _ANIMATED_STRIP_LIMIT:
            logger.info("Image %s has %d animations; showing the first %d",
                        row["prompt_id"], len(videos), _ANIMATED_STRIP_LIMIT)
        return [
            (v["prompt_id"], animated_preview_path(v, COMFYUI_OUTPUT_DIR, THUMB_DIR),
             v.get("thumbnail_path"))
            for v in videos[:_ANIMATED_STRIP_LIMIT]
        ]

    def _video_rows(self) -> list[dict]:
        return [r for r in self._db.list_generations() if media_type_of_row(r) == "video"]

    # --- Send to Evolver: hand a displayed video to the sibling pipeline -------

    def _update_evolver_button(self, preview):
        """Reflect the displayed generation on the Send-to-Evolver button.

        Shown only when the generation is a video with a file on disk; Evolver is
        a video pipeline, so for an image or a missing file the button is hidden.
        A video already sent shows a persistent, disabled "Sent ✓" (the flag is
        read from the row, which the DB persists). ``preview`` is the resolved
        ``(path, media_type)``, or ``None``."""
        is_video = preview is not None and preview[1] == "video"
        self._evolver_btn.setVisible(is_video)
        if not is_video:
            return
        already_sent = bool(self._displayed_row and self._displayed_row.get("evolver_exported_at"))
        self._evolver_btn.setText("Sent to Evolver ✓" if already_sent else "Send to Evolver")
        self._evolver_btn.setEnabled(not already_sent)

    def _displayed_video_path(self) -> Path | None:
        """The on-disk video file backing the displayed generation, or ``None``
        when it isn't a video (or its file is missing). Resolved fresh, so a file
        deleted since selection is caught. Shared by Send-to-Evolver and OSR2 drive."""
        if not self._displayed_row:
            return None
        preview = resolve_preview(self._displayed_row, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != "video":
            return None
        return preview[0]

    # --- Drive OSR2: stream this video's funscript to the device ---------------

    def _update_osr2_button(self, preview):
        """Show "Drive OSR2" only for a displayed video that has a funscript.

        Any change of the displayed media first ends a drive in progress — unchecking
        emits ``osr2_drive_toggled(False)`` so the view stops and parks the device —
        so enabling is always a fresh, explicit opt-in for the video now on screen."""
        scripted = (
            preview is not None and preview[1] == "video"
            and funscript_path_for(preview[0]).exists()
        )
        if self._osr2_btn.isChecked():
            self._osr2_btn.setChecked(False)
        self._osr2_btn.setVisible(scripted)

    def _on_osr2_toggled(self, checked: bool):
        self._osr2_btn.setText("Driving OSR2 — click to stop" if checked else "Drive OSR2")
        self.osr2_drive_toggled.emit(checked)

    def stop_osr2_drive(self):
        """Turn Drive OSR2 off if it's on — the off-toggle stops and parks the device.

        Called when the tab is left, so only the front tab's video ever drives."""
        if self._osr2_btn.isChecked():
            self._osr2_btn.setChecked(False)

    def osr2_drive_target(self):
        """``(player, actions)`` to drive the OSR2 from the shown video, or ``None``.

        The view calls this when the tab enables driving: the media player to follow
        and the funscript actions beside the video. ``None`` if the video or its
        script has gone since it was shown."""
        path = self._displayed_video_path()
        if path is None:
            return None
        actions = read_actions(funscript_path_for(path))
        if not actions:
            return None
        return self._preview.player(), actions

    def _on_send_to_evolver(self):
        """Copy the displayed video into Evolver's inbox and remember the send.

        Re-checks the persisted flag (not just the button's disabled state) so the
        handoff can't be repeated. The copy lands in another app's inbox with no
        other visible result here, so a failure must surface loudly."""
        if not self._displayed_row or self._displayed_row.get("evolver_exported_at"):
            return
        path = self._displayed_video_path()
        if path is None:
            return
        try:
            evolver_export.export_video(path, EVOLVER_INBOX_DIR / EVOLVER_SOURCE)
        except Exception as e:
            logger.exception("Failed to send %s to Evolver", path)
            QMessageBox.warning(
                self._preview, "Send to Evolver failed",
                f"Could not send this video to Evolver:\n\n{e}",
            )
            return
        prompt_id = self._displayed_row["prompt_id"]
        self._db.mark_evolver_exported(prompt_id)
        # Re-read so the row (and thus the button) reflects the persisted send.
        self._displayed_row = self._db.get_generation(prompt_id) or self._displayed_row
        self._update_evolver_button((path, "video"))
