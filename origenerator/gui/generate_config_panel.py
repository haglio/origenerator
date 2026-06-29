import json
import logging
import uuid
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QScrollArea,
)
from PyQt6.QtCore import pyqtSignal

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import config_folder_label
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui.param_form import ParamForm
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

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        layout.addWidget(self._scroll, 1)

        bottom = QVBoxLayout()
        self._status_label = QLabel("Ready")
        bottom.addWidget(self._status_label)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        bottom.addWidget(self._progress)
        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setObjectName("generateBtn")
        self._generate_btn.clicked.connect(self._on_generate)
        btn_row.addStretch()
        btn_row.addWidget(self._generate_btn)
        bottom.addLayout(btn_row)
        layout.addLayout(bottom)

        self._on_workflow_changed()

    def _connect_signals(self):
        self._client.progress.connect(self._on_progress)
        self._client.job_completed.connect(self._on_completed)
        self._client.job_error.connect(self._on_error)
        self._client.connected.connect(self._on_connected)
        self._client.disconnected.connect(self._on_disconnected)

    def teardown(self):
        """Disconnect from the shared client before the panel is destroyed."""
        for signal, slot in (
            (self._client.progress, self._on_progress),
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
        self._status_label.setText("Connected to ComfyUI")

    def _on_disconnected(self):
        self._status_label.setText("Disconnected")

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
            self._status_label.setText(
                f"Select an input image ({', '.join(missing_images)}) before generating."
            )
            return

        # Build the job now (fixing the seed), but let the queue decide when it runs.
        self._prepared = {
            "workflow": wf,
            "params": params,
            "payload": wf.build_api_payload(params),
            "prompt_id": str(uuid.uuid4()),
        }
        self._generate_btn.setEnabled(False)
        if self._queue is not None:
            self._status_label.setText("Queued…")
            self._queue.submit(self, wf.name)
        else:
            self._begin_job()

    def run_now(self):
        """Start the prepared job — called by the queue when it reaches the head."""
        self._begin_job()

    def _begin_job(self):
        job = self._prepared
        if job is None:
            return
        wf, params = job["workflow"], job["params"]
        prompt_id, payload = job["prompt_id"], job["payload"]
        self._prepared = None

        self._db.insert_generation(
            prompt_id=prompt_id,
            workflow_name=wf.name,
            workflow_version=wf.version,
            positive_prompt=params.get("positive_prompt", ""),
            negative_prompt=params.get("negative_prompt", ""),
            seed=params.get("seed"),
            params_json=json.dumps(params),
            workflow_json=json.dumps(payload),
        )

        try:
            actual_pid = self._client.submit_job(payload)
            self._client_prompt_id = prompt_id
            self._comfy_prompt_id = actual_pid
            self._submitted_workflow = wf
            self._db.update_generation(prompt_id, status="running")
            self._status_label.setText(f"Generating... (job {actual_pid[:8]})")
            self._progress.setValue(0)
        except Exception as e:
            logger.error("Failed to submit job: %s", e)
            self._db.update_generation(prompt_id, status="error", error_message=str(e))
            self._status_label.setText(f"Error: {e}")
            self._generate_btn.setEnabled(True)
            self._release_queue_slot()

    def set_queue_status(self, position: int, eta_seconds: float):
        """Show this panel's place in line and a countdown to its turn."""
        text = f"Queued (#{position})"
        if eta_seconds and eta_seconds > 0:
            text += f" — starts in ~{format_duration(eta_seconds)}"
        self._status_label.setText(text)

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
                thumb_path = str(generate_thumbnail(source, wf.output_type, THUMB_DIR))

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
            self._status_label.setText(f"Done in {format_duration(duration)}")
        else:
            self._status_label.setText("Done!")
        self._progress.setValue(self._progress.maximum())
        self._generate_btn.setEnabled(True)
        completed_id = self._client_prompt_id
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
        self._status_label.setText(f"Error: {error_msg[:100]}")
        self._generate_btn.setEnabled(True)
        self._reset_job()
        self._release_queue_slot()

    def _reset_job(self):
        self._client_prompt_id = None
        self._comfy_prompt_id = None
        self._submitted_workflow = None

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
        """The tab title: the user's custom name, else the config's gallery folder."""
        if self._custom_title:
            return self._custom_title
        params = self._param_form.get_values_static() if self._param_form else {}
        return config_folder_label(self._workflow_combo.currentData(), params)

    def set_custom_title(self, name: str):
        """Pin a user-chosen tab name that overrides the auto gallery-folder name."""
        self._custom_title = name
        self._emit_title()

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
