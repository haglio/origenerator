from PyQt6.QtWidgets import QMainWindow, QTabWidget
from PyQt6.QtGui import QIcon

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.fonts import FONT_UI, SIZE_HEADING, make_font

from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import PROJECT_DIR
from origenerator.db import Database
from origenerator.gui.generate_view import GenerateView
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.stylesheet import build_stylesheet

_GENERATE_TABS_KEY = "generate_tabs"
_GALLERY_FOLDER_KEY = "gallery_folder"


class OrigeneratorWindow(QMainWindow):
    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self._app_state = app_state
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
        self._gallery_view.replay_requested.connect(self._on_replay)
        self._restore_session()

    def _on_reuse(self, workflow_name: str, params: dict):
        self._generate_view.open_config(workflow_name, params)
        self._tabs.setCurrentWidget(self._generate_view)

    def _on_replay(self, row: dict, overrides: dict):
        self._generate_view.submit_replay(row, overrides)
        self._tabs.setCurrentWidget(self._generate_view)

    def _restore_session(self):
        """Reopen the Generate subtabs and Gallery folder from the last session."""
        tabs = self._app_state.get(_GENERATE_TABS_KEY)
        if tabs:
            self._generate_view.restore_state(tabs)
        self._gallery_view.select_folder(self._app_state.get(_GALLERY_FOLDER_KEY))

    def closeEvent(self, event):
        """Persist the open Generate subtabs and Gallery folder on the way out."""
        self._app_state.set(_GENERATE_TABS_KEY, self._generate_view.capture_state())
        self._app_state.set(_GALLERY_FOLDER_KEY, self._gallery_view.selected_folder())
        self._app_state.save()
        super().closeEvent(event)
