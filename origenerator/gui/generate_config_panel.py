import json
import logging
import uuid
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import pyqtSignal

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import config_tab_title, settings_signature
from origenerator.generation_config import (
    ConfigSnapshot, find_duplicate_generation, randomize_seeds,
)
from origenerator.gui.param_form import ParamForm
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.thumbnail import generate_thumbnail
from origenerator.timing import (
    estimate_label,
    execution_duration_seconds,
    format_duration,
)
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR

logger = logging.getLogger(__name__)


class GenerateConfigPanel(QWidget):
    """One generation configuration: pick a workflow, set params, run a job.

    Several panels share a single ComfyUIClient, so each filters the client's
    signals down to its own in-flight job. ``generation_completed`` fires (with
    our DB prompt id) when a job finishes so a container can refresh its strip.
    """

    generation_completed = pyqtSignal(str)  # our (client-side) prompt_id
    title_changed = pyqtSignal(str)         # current tab title

    def __init__(self, client: ComfyUIClient, db: Database, queue=None, parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db
        self._queue = queue                          # serializes jobs across panels; None = run at once
        self._client_prompt_id: str | None = None   # our uuid; the DB row key
        self._comfy_prompt_id: str | None = None     # ComfyUI's id; keys its signals
        self._submitted_workflow = None              # workflow captured at submit time
        self._prepared: dict | None = None           # a job built but not yet started
        self._custom_title: str | None = None        # user-set name; overrides the auto title
        self._bar_state = "ready"                     # drives the progress bar's text + color
        self._executing = False                        # has ComfyUI started our prompt yet?
        self._strip_ids: list[str] = []               # this tab's strip: seeded folder + its own runs, newest first
        self._param_form: ParamForm | None = None
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Workflow:"))
        self._workflow_combo = QComboBox()
        for key, wf in WORKFLOW_REGISTRY.items():
            self._workflow_combo.addItem(wf.display_name, key)
        self._workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)
        header.addWidget(self._workflow_combo, 1)
        layout.addLayout(header)

        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        layout.addWidget(self._estimate_label)

        # The settings form sits beside a live preview that mirrors the job in
        # progress (ComfyUI's preview frames) and then the finished output.
        body = QHBoxLayout()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        body.addWidget(self._scroll, 3)
        self._preview = PreviewWidget()
        body.addWidget(self._preview, 2)
        layout.addLayout(body, 1)

        bottom = QVBoxLayout()
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        bottom.addWidget(self._progress)
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
        bottom.addLayout(btn_row)
        layout.addLayout(bottom)

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

        # Guard against silently re-running an identical job: a pinned (non-random)
        # seed that matches a past generation would just re-create it byte-for-byte.
        snapshot = ConfigSnapshot(key, params, self._param_form.seed_is_random())
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

    def _prepare_job(self, *, payload: dict, workflow, queue_name: str, record: dict):
        """Stage a built job, then hand it to the queue (or run it now if unqueued).

        ``workflow`` is the WorkflowTemplate this job was built from, captured so
        its output node is used when the job completes.
        """
        self._prepared = {"payload": payload, "workflow": workflow, "record": record}
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

    def _begin_job(self):
        job = self._prepared
        if job is None:
            return
        self._prepared = None
        record = job["record"]
        prompt_id = record["prompt_id"]
        self._db.insert_generation(**record)

        try:
            actual_pid = self._client.submit_job(job["payload"])
            self._client_prompt_id = prompt_id
            self._comfy_prompt_id = actual_pid
            self._submitted_workflow = job["workflow"]
            self._db.update_generation(prompt_id, status="running")
            self._preview.clear()  # a fresh job: drop the previous result
            self._show_running()
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
        return self._comfy_prompt_id is not None and prompt_id == self._comfy_prompt_id

    def _on_progress(self, prompt_id: str, value: int, max_val: int):
        if not self._is_mine(prompt_id):
            return
        if max_val > 0:
            self._progress.setRange(0, max_val)
            self._progress.setValue(value)

    def _on_node_executing(self, prompt_id: str, _node_id: str):
        # ComfyUI has begun running our prompt (vs. it merely sitting in the
        # server queue, behind e.g. a gallery re-roll). This decides whether
        # Cancel interrupts the run or just dequeues it. ``executing`` precedes
        # any ``progress`` for the prompt, so it's the earliest signal we get.
        if self._is_mine(prompt_id):
            self._executing = True

    def _on_preview(self, prompt_id: str, data: bytes):
        if self._is_mine(prompt_id):
            self._preview.show_frame(data)

    def _on_completed(self, prompt_id: str, history_data: dict):
        if not self._is_mine(prompt_id):
            return
        wf = self._submitted_workflow
        if not wf:
            return
        files = wf.extract_output_info(history_data)

        thumb_path = None
        if files:
            first = files[0]
            subfolder = first.get("subfolder", "")
            source = COMFYUI_OUTPUT_DIR / subfolder / first["filename"]
            if source.exists():
                THUMB_DIR.mkdir(parents=True, exist_ok=True)
                thumb_path = str(generate_thumbnail(
                    source, wf.output_type, THUMB_DIR, name=self._client_prompt_id
                ))
                self._preview.show_media(source, wf.output_type)

        now = datetime.now(timezone.utc).isoformat()
        duration = execution_duration_seconds(history_data)
        fields = dict(
            status="completed",
            output_files=json.dumps(files),
            thumbnail_path=thumb_path,
            completed_at=now,
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
        self._reset_job()
        self.generation_completed.emit(completed_id)
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
        staged = self._prepared is not None
        comfy_id = self._comfy_prompt_id
        if self._queue is not None and (staged or comfy_id is not None):
            self._queue.cancel(self)  # drop our slot (pending or the running head)
        if comfy_id is not None:
            try:
                if self._executing:
                    self._client.interrupt()
                else:
                    self._client.cancel_prompt(comfy_id)
            except Exception as e:
                logger.warning("Cancel failed for %s: %s", comfy_id, e)
            if self._client_prompt_id:
                self._db.delete_generation(self._client_prompt_id)
        elif not staged:
            return  # nothing in flight to cancel
        self._prepared = None
        self._reset_job()
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._show_canceled()

    def _reset_job(self):
        self._client_prompt_id = None
        self._comfy_prompt_id = None
        self._submitted_workflow = None
        self._executing = False

    def settings_key(self) -> tuple[str, str] | None:
        """The gallery settings-folder this config maps to: (workflow, signature).

        The signature mirrors how a generation is stored — the form values plus
        the workflow's non-form defaults, minus seeds — so it matches the folder
        this tab's outputs land in, and groups reruns that differ only by seed.
        ``None`` when no workflow is selected.
        """
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        if wf is None or self._param_form is None:
            return None
        params = self._param_form.get_values_static()
        for name, value in wf.default_params().items():
            params.setdefault(name, value)
        return key, settings_signature(json.dumps(params))

    def strip_ids(self) -> list[str]:
        """The generations to show in this tab's strip, newest first.

        An accumulating history: whatever folder the tab was seeded with plus
        every generation it has produced since — including ones whose settings no
        longer match the current form, so tweaks-and-regenerate stays visible.
        """
        return list(self._strip_ids)

    def seed_strip(self, prompt_ids):
        """Seed the strip with a settings folder when the tab opens from one."""
        self._strip_ids = list(prompt_ids)

    def current_config(self) -> ConfigSnapshot:
        """Snapshot the live settings for comparison (without randomizing the seed)."""
        if self._param_form is None:
            return ConfigSnapshot(self._workflow_combo.currentData(), {}, False)
        return ConfigSnapshot(
            self._workflow_combo.currentData(),
            self._param_form.get_values_static(),
            self._param_form.seed_is_random(),
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

        Like :meth:`prefill`, but also restores the seed's Random state so a tab
        the user left on Random comes back random instead of pinned to the stale
        seed that was in the field at save time.
        """
        self.prefill(snapshot.workflow_name, snapshot.params)
        if self._param_form:
            self._param_form.set_seed_random(snapshot.seed_is_random)
