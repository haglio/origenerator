import json
import logging
import uuid
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QScrollArea,
)
from PyQt6.QtCore import Qt

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.param_form import ParamForm
from origenerator.thumbnail import generate_thumbnail
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR

logger = logging.getLogger(__name__)


class GenerateView(QWidget):
    def __init__(self, client: ComfyUIClient, db: Database, parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db
        self._current_prompt_id: str | None = None
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
        self._client.connected.connect(lambda: self._status_label.setText("Connected to ComfyUI"))
        self._client.disconnected.connect(lambda: self._status_label.setText("Disconnected"))

    def _on_workflow_changed(self):
        key = self._workflow_combo.currentData()
        if key and key in WORKFLOW_REGISTRY:
            wf = WORKFLOW_REGISTRY[key]
            self._param_form = ParamForm(wf.param_definitions())
            self._scroll.setWidget(self._param_form)

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

        payload = wf.build_api_payload(params)
        prompt_id = str(uuid.uuid4())

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
            # ComfyUI assigns its own prompt_id; update our record
            if actual_pid != prompt_id:
                self._db.update_generation(prompt_id, status="running")
                # We track by our own prompt_id but store the mapping
                self._current_prompt_id = prompt_id
                self._comfyui_prompt_id = actual_pid
            else:
                self._current_prompt_id = prompt_id
                self._comfyui_prompt_id = prompt_id
                self._db.update_generation(prompt_id, status="running")
            self._status_label.setText(f"Generating... (job {actual_pid[:8]})")
            self._progress.setValue(0)
            self._generate_btn.setEnabled(False)
        except Exception as e:
            logger.error("Failed to submit job: %s", e)
            self._db.update_generation(prompt_id, status="error", error_message=str(e))
            self._status_label.setText(f"Error: {e}")

    def _on_progress(self, prompt_id: str, value: int, max_val: int):
        if max_val > 0:
            self._progress.setRange(0, max_val)
            self._progress.setValue(value)

    def _on_completed(self, prompt_id: str, history_data: dict):
        if not self._current_prompt_id:
            return
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
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
        self._db.update_generation(
            self._current_prompt_id,
            status="completed",
            output_files=json.dumps(files),
            thumbnail_path=thumb_path,
            completed_at=now,
        )
        self._status_label.setText("Done!")
        self._progress.setValue(self._progress.maximum())
        self._generate_btn.setEnabled(True)
        self._current_prompt_id = None

    def _on_error(self, prompt_id: str, error_msg: str):
        if self._current_prompt_id:
            self._db.update_generation(
                self._current_prompt_id,
                status="error",
                error_message=error_msg,
            )
        self._status_label.setText(f"Error: {error_msg[:100]}")
        self._generate_btn.setEnabled(True)
        self._current_prompt_id = None

    def prefill_params(self, params: dict):
        if self._param_form:
            self._param_form.set_values(params)
