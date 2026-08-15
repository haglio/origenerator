import base64

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut

from origenerator.app_state import AppState
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import PROJECT_DIR
from origenerator.db import Database
from origenerator.experiments.background import cancel_experiments
from origenerator.gui.gallery_view import GalleryView

# The open editable config tabs (in the gallery's info pane). Kept under its
# historical key so sessions saved before the Generate/Gallery merge still restore.
_CONFIG_TABS_KEY = "generate_tabs"
_GALLERY_FOLDER_KEY = "gallery_folder"
_GALLERY_SELECTION_KEY = "gallery_selection"
_GALLERY_COMBINE_KEY = "gallery_combine"
_GEOMETRY_KEY = "window_geometry"
_OSR2_ENABLED_KEY = "osr2_enabled"
_EXPERIMENTS_ENABLED_KEY = "experiments_enabled"
_AUDIO_ENABLED_KEY = "audio_enabled"


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
        icon_path = PROJECT_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # One unified view: the gallery, whose info pane now holds the editable
        # config tabs that used to be a separate Generate tab. Reuse Parameters,
        # the re-roll "+", and the combine panel all feed it.
        self._gallery_view = GalleryView(db, client=client)
        self.setCentralWidget(self._gallery_view)

        # Ctrl+Alt+Q quits from anywhere in the app: an application-scoped shortcut
        # fires no matter which widget holds focus. close() runs closeEvent — which
        # persists the session and geometry — and the app exits on the last window
        # closing, releasing the OSR2 via aboutToQuit.
        quit_shortcut = QShortcut(QKeySequence("Ctrl+Alt+Q"), self)
        quit_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_shortcut.activated.connect(self.close)

        self._restore_session()
        # Background experiments belong to the closed app, so the ones the last
        # absence left in ComfyUI's queue are dropped before anything is adopted:
        # an open app never has one competing for the GPU. The live install's
        # alone, both ends of it — a branch session's database is a copy of the
        # live one, so the rows it would clear are the live app's experiments
        # running in the ComfyUI they share.
        if not is_branch_session():
            cancel_experiments(db, client)
        # Reconnect to any generation left running by the previous session. A tab's
        # Generate is itself a re-roll, so every in-flight row is the gallery's to
        # re-adopt — the tabs restore their configs only, owning no jobs.
        self._gallery_view.reconnect_running_rerolls()
        # With experiments waiting for review, open on their shelf instead of the
        # saved folder — presenting what came up while the user was away is the
        # whole point of the background experimenter.
        self._gallery_view.present_pending_experiments()

    def _restore_session(self):
        """Put the window back where it was — same monitor, size, and maximized
        state — and reopen the last session's config tabs, gallery folder, and
        selected generation."""
        self._restore_geometry()
        self._gallery_view.restore_config_tabs(self._app_state.get(_CONFIG_TABS_KEY))
        self._gallery_view.select_folder(self._app_state.get(_GALLERY_FOLDER_KEY))
        self._gallery_view.select_generation(self._app_state.get(_GALLERY_SELECTION_KEY))
        self._gallery_view.restore_combine_selection(self._app_state.get(_GALLERY_COMBINE_KEY))
        self._gallery_view.set_osr2_enabled(self._app_state.get(_OSR2_ENABLED_KEY))
        self._gallery_view.set_experiments_enabled(
            self._app_state.get(_EXPERIMENTS_ENABLED_KEY))
        self._gallery_view.set_audio_enabled(self._app_state.get(_AUDIO_ENABLED_KEY))

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
        """Hand ComfyUI the background experiments for the coming absence, then
        persist the session (open config tabs, gallery folder/selection) and the
        window geometry so the next launch reopens as it was."""
        self._gallery_view.queue_experiments_for_absence()
        self._app_state.set(_CONFIG_TABS_KEY, self._gallery_view.capture_config_tabs())
        self._app_state.set(_GALLERY_FOLDER_KEY, self._gallery_view.selected_folder())
        self._app_state.set(_GALLERY_SELECTION_KEY, self._gallery_view.selected_generation())
        self._app_state.set(_GALLERY_COMBINE_KEY, self._gallery_view.combine_selection())
        self._app_state.set(_OSR2_ENABLED_KEY, self._gallery_view.osr2_enabled())
        self._app_state.set(
            _EXPERIMENTS_ENABLED_KEY, self._gallery_view.experiments_enabled())
        self._app_state.set(_AUDIO_ENABLED_KEY, self._gallery_view.audio_enabled())
        self._app_state.set(
            _GEOMETRY_KEY,
            base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
        )
        self._app_state.save()
        super().closeEvent(event)
