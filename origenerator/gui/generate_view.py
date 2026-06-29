from PyQt6.QtWidgets import QWidget, QVBoxLayout

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generate_config_panel import GenerateConfigPanel


class GenerateView(QWidget):
    def __init__(self, client: ComfyUIClient, db: Database, parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._panel = GenerateConfigPanel(client, db)
        layout.addWidget(self._panel)

    def prefill_params(self, workflow_name: str, params: dict):
        self._panel.prefill(workflow_name, params)
