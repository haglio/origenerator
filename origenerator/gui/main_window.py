import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PyQt6.QtWidgets import QMainWindow, QTabWidget
from PyQt6.QtGui import QIcon

from shared_ui.fonts import FONT_UI, SIZE_HEADING, make_font

from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import PROJECT_DIR
from origenerator.db import Database
from origenerator.gui.generate_view import GenerateView
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.stylesheet import build_stylesheet


class OrigeneratorWindow(QMainWindow):
    def __init__(self, client: ComfyUIClient, db: Database, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Origenerator")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(build_stylesheet())
        icon_path = PROJECT_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._tabs = QTabWidget()
        self._tabs.setFont(make_font(FONT_UI, SIZE_HEADING))
        self.setCentralWidget(self._tabs)

        self._generate_view = GenerateView(client, db)
        self._gallery_view = GalleryView(db)
        self._tabs.addTab(self._generate_view, "Generate")
        self._tabs.addTab(self._gallery_view, "Gallery")

        self._gallery_view.reuse_requested.connect(self._on_reuse)

    def _on_reuse(self, workflow_name: str, params: dict):
        self._generate_view.prefill_params(workflow_name, params)
        self._tabs.setCurrentWidget(self._generate_view)
