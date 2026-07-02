import json
import logging
import uuid
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter,
    QComboBox, QPushButton, QProgressBar, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.comfyui_client import ComfyUIClient
from origenerator.completion import extract_completion
from origenerator.db import Database
from origenerator.gallery import (
    config_tab_title, media_type_of_row, output_file_reference,
    settings_signature, source_image_id_for,
)
from origenerator.generation_config import (
    ConfigSnapshot, find_duplicate_generation, prepared_params, randomize_seeds,
)
from origenerator.gui.generation_job import GenerationJob, persist_generation
from origenerator.gui.param_form import ParamForm
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.thumbnail_strip import ThumbnailStrip
from origenerator.progress import ProgressTracker
from origenerator.timing import estimate_label, format_duration
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR

logger = logging.getLogger(__name__)


class GenerateConfigPanel(QWidget):
    """One generation configuration: pick a workflow, set params, run a job.

    Several panels share a single ComfyUIClient, so each filters the client's
    signals down to its own in-flight job. The panel lays out its three resizable
    panes itself — this tab's own strip of past runs (left), the settings and run
    controls (middle), and a live preview (right) — so the tab row spans all
    three. Clicking a strip thumbnail re-emits its prompt id via
    ``strip_activated`` so a container can open (or reuse) a tab for it.
    """

    title_changed = pyqtSignal(str)     # current tab title
    strip_activated = pyqtSignal(str)   # a strip thumbnail was clicked (prompt_id)

    def __init__(self, client: ComfyUIClient, db: Database, queue=None, parent=None):
        super().__init__(parent)
        self._client = client
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
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Three resizable panes, their dividers doubling as drag handles like the
        # Gallery: this tab's strip of past runs (left), the settings and run
        # controls (middle), and a live preview (right).
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)

        # Left pane: this tab's own accumulating strip of past runs.
        self._strip = ThumbnailStrip(self._db)
        self._strip.thumbnail_activated.connect(self.strip_activated)
        self._panes.addWidget(self._strip)

        # Middle pane: workflow picker, settings form, and the run controls. The
        # progress bar and buttons live here, so they span only the settings —
        # never the preview.
        main = QWidget()
        main_box = QVBoxLayout(main)
        main_box.setContentsMargins(0, 0, 0, 0)
        main_box.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(QLabel("Workflow:"))
        self._workflow_combo = QComboBox()
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
        main_box.addWidget(self._scroll, 1)
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
        self._panes.addWidget(main)

        # Right pane: a live preview mirroring the job in progress (ComfyUI's
        # preview frames) and then its finished output.
        self._preview = PreviewWidget()
        self._panes.addWidget(self._preview)

        # The strip holds its width; the settings and preview panes grow with the
        # window (settings faster), mirroring the Gallery's proportions. The floors
        # stay low enough that the whole window can still tile into a monitor third
        # or a portrait-monitor half.
        main.setMinimumWidth(240)
        self._preview.setMinimumWidth(180)
        self._panes.setStretchFactor(0, 0)
        self._panes.setStretchFactor(1, 3)
        self._panes.setStretchFactor(2, 2)
        self._panes.setSizes([210, 480, 320])

        layout.addWidget(self._panes)

        self._on_workflow_changed()

    def _connect_signals(self):
        self._client.progress.connect(self._on_progress)
        self._client.node_executing.connect(self._on_node_executing)
        self._client.preview_image.connect(self._on_preview)
        self._client.job_completed.connect(self._on_completed)
        self._client.job_error.connect(self._on_error)
        self._client.connected.connect(self._on_connected)
        self._client.disconnected.connect(self._on_disconnected)

    def teardown(self):
        """Disconnect from the shared client before the panel is destroyed."""
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
        key = self._workflow_combo.currentData()
        if not key or key not in WORKFLOW_REGISTRY:
            return
        wf = WORKFLOW_REGISTRY[key]
        params = self._param_form.get_values()
        # Merge in non-form params (checkpoint, vae, etc.) from defaults
        defaults = wf.default_params()
        for k, v in defaults.items():
            if k not in params:
                params[k] = v

        missing_images = [
            pd.label for pd in wf.param_definitions()
            if pd.type == "image" and not str(params.get(pd.key, "")).strip()
        ]
        if missing_images:
            self._show_ready(
                f"Select an input image ({', '.join(missing_images)}) before generating."
            )
            return

        # "Random" input image: regenerate a fresh input of the same kind first,
        # then run the main job on it (the box shows only for a reproducible input).
        if self._param_form.image_is_random():
            self._generate_random_input_then_run(wf, params)
        else:
            self._generate(wf, params)

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
            if not self._offer_reroll(wf):
                return  # let the user change something rather than duplicate it
            params = randomize_seeds(params, wf.seed_keys())
            self._param_form.set_seed_random(True)

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
        job = GenerationJob(self._client, image_wf, prepared_params(source_row, image_wf))
        self._input_image_job = job
        job.preview.connect(self._preview.show_frame)  # watch the frame take shape
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

    def _offer_reroll(self, wf) -> bool:
        """Warn that this exact config was already generated; ask whether to re-roll.

        Re-running it would just re-create an identical output, so the only
        useful choices are a fresh random seed or backing out to change a
        setting. Returns ``True`` to re-roll with a new random seed, ``False`` to
        cancel (also the dialog's close box).
        """
        media = wf.output_type if wf.output_type in ("image", "video") else "output"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Already generated")
        box.setText(
            f"You've already generated this exact {media} — same settings and "
            f"the same seed.\nRunning it again will just re-create an identical "
            f"{media}."
        )
        box.setInformativeText("Generate a new random seed instead, or cancel to change a setting?")
        reroll = box.addButton("New Random Seed", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(reroll)
        box.exec()
        return box.clickedButton() is reroll

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
        return key, settings_signature(key, json.dumps(params))

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
