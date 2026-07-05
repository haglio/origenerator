import base64

from PyQt6.QtCore import QByteArray
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtGui import QIcon

from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import PROJECT_DIR
from origenerator.db import Database
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.stylesheet import build_stylesheet

# The open editable config tabs (in the gallery's info pane). Kept under its
# historical key so sessions saved before the Generate/Gallery merge still restore.
_CONFIG_TABS_KEY = "generate_tabs"
_GALLERY_FOLDER_KEY = "gallery_folder"
_GALLERY_SELECTION_KEY = "gallery_selection"
_GALLERY_COMBINE_KEY = "gallery_combine"
_GEOMETRY_KEY = "window_geometry"


class OrigeneratorWindow(QMainWindow):
    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self.setWindowTitle("Origenerator")
        # A small floor (not the old 1000x700) so a tiling window manager can snap
        # the window into a monitor third (~853px) or a portrait-monitor half
        # (~720px) — Qt maps this straight to the window's min track size. The
        # gallery's own pane floors keep content readable at those slot sizes; only
        # a manual drag below that compresses it.
        self.setMinimumSize(600, 400)
        self.setStyleSheet(build_stylesheet())
        icon_path = PROJECT_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # One unified view: the gallery, whose info pane now holds the editable
        # config tabs that used to be a separate Generate tab. Reuse Parameters,
        # the re-roll "+", and the combine panel all feed it.
        self._gallery_view = GalleryView(db, client=client)
        self.setCentralWidget(self._gallery_view)

        self._restore_session()
        # Reconnect to any generation left running by the previous session. A tab's
        # Generate is itself a re-roll, so every in-flight row is the gallery's to
        # re-adopt — the tabs restore their configs only, owning no jobs.
        self._gallery_view.reconnect_running_rerolls()

    def _restore_session(self):
        """Put the window back where it was — same monitor, size, and maximized
        state — and reopen the last session's config tabs, gallery folder, and
        selected generation."""
        self._restore_geometry()
        self._gallery_view.restore_config_tabs(self._app_state.get(_CONFIG_TABS_KEY))
        self._gallery_view.select_folder(self._app_state.get(_GALLERY_FOLDER_KEY))
        self._gallery_view.select_generation(self._app_state.get(_GALLERY_SELECTION_KEY))
        self._gallery_view.restore_combine_selection(self._app_state.get(_GALLERY_COMBINE_KEY))

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
        """Persist the session (open config tabs, gallery folder/selection) and the
        window geometry so the next launch reopens as it was."""
        self._app_state.set(_CONFIG_TABS_KEY, self._gallery_view.capture_config_tabs())
        self._app_state.set(_GALLERY_FOLDER_KEY, self._gallery_view.selected_folder())
        self._app_state.set(_GALLERY_SELECTION_KEY, self._gallery_view.selected_generation())
        self._app_state.set(_GALLERY_COMBINE_KEY, self._gallery_view.combine_selection())
        self._app_state.set(
            _GEOMETRY_KEY,
            base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
        )
        self._app_state.save()
        super().closeEvent(event)
