import base64

from PyQt6.QtCore import QByteArray
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
_GALLERY_SELECTION_KEY = "gallery_selection"
_ACTIVE_TAB_KEY = "active_tab"
_GEOMETRY_KEY = "window_geometry"


class OrigeneratorWindow(QMainWindow):
    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self.setWindowTitle("Origenerator")
        # A small floor (not the old 1000x700) so a tiling window manager can snap
        # the window into a monitor third (~853px) or a portrait-monitor half
        # (~720px) — Qt maps this straight to the window's min track size. The tab
        # widgets' own content minimum is ~660px (their pane/label/combo floors),
        # so content renders fully at those slot sizes; only a manual drag below
        # that compresses it.
        self.setMinimumSize(600, 400)
        self.setStyleSheet(build_stylesheet())
        icon_path = PROJECT_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._tabs = QTabWidget()
        self._tabs.setFont(make_font(FONT_UI, SIZE_HEADING))
        self.setCentralWidget(self._tabs)

        self._generate_view = GenerateView(client, db)
        # The gallery skips re-roll rows a Generate tab already owns, so the two
        # never both track one job; the tabs claim theirs during _restore_session.
        self._gallery_view = GalleryView(
            db, client=client, claimed_ids=self._generate_view.active_prompt_ids
        )
        self._tabs.addTab(self._generate_view, "Generate")
        self._tabs.addTab(self._gallery_view, "Gallery")

        self._gallery_view.reuse_requested.connect(self._on_reuse)
        self._restore_session()
        # After the tabs have reclaimed their own running jobs, adopt whatever
        # in-flight re-rolls remain from the previous session.
        self._gallery_view.reconnect_running_rerolls()

    def _on_reuse(self, workflow_name: str, params: dict):
        self._generate_view.open_config(workflow_name, params)
        self._tabs.setCurrentWidget(self._generate_view)

    def _restore_session(self):
        """Reopen the Generate subtabs, Gallery folder, and active tab, and
        put the window back where it was — same monitor, size, and maximized
        state — when it was last closed."""
        self._restore_geometry()
        tabs = self._app_state.get(_GENERATE_TABS_KEY)
        if tabs:
            self._generate_view.restore_state(tabs)
        self._gallery_view.select_folder(self._app_state.get(_GALLERY_FOLDER_KEY))
        self._gallery_view.select_generation(self._app_state.get(_GALLERY_SELECTION_KEY))
        active = self._app_state.get(_ACTIVE_TAB_KEY)
        if isinstance(active, int) and 0 <= active < self._tabs.count():
            self._tabs.setCurrentIndex(active)

    def _restore_geometry(self):
        """Reapply the saved window geometry: screen, size, and maximized state.

        Qt's ``saveGeometry`` blob is stored base64-encoded in the JSON state.
        A missing or corrupt value just leaves the window at its default size.
        """
        blob = self._app_state.get(_GEOMETRY_KEY)
        if not isinstance(blob, str):
            return
        try:
            self.restoreGeometry(QByteArray(base64.b64decode(blob)))
        except ValueError:
            pass  # corrupt/hand-edited state — fall back to the default size

    def closeEvent(self, event):
        """Persist the session (open tabs, gallery folder/selection, active
        tab) and the window geometry so the next launch reopens as it was."""
        self._app_state.set(_GENERATE_TABS_KEY, self._generate_view.capture_state())
        self._app_state.set(_GALLERY_FOLDER_KEY, self._gallery_view.selected_folder())
        self._app_state.set(_GALLERY_SELECTION_KEY, self._gallery_view.selected_generation())
        self._app_state.set(_ACTIVE_TAB_KEY, self._tabs.currentIndex())
        self._app_state.set(
            _GEOMETRY_KEY,
            base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
        )
        self._app_state.save()
        super().closeEvent(event)
