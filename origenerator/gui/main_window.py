import base64
import logging

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut

from origenerator.app_state import AppState
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import PROJECT_DIR
from origenerator.db import Database
from origenerator.base_backfill import cancel_base_renders, fold_completed_base_renders
from origenerator.experiments.background import cancel_experiments
from origenerator.win32 import place_window_in_device_pixels
from origenerator.fun_time_mode import FunTimeSession
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.prompt_box import PROMPT_HEIGHTS

logger = logging.getLogger(__name__)

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
# The mic switch. Absent from a session saved before it was persisted — and from
# a first launch — which is the app's default of on (see set_mic_enabled).
_MIC_ENABLED_KEY = "mic_enabled"
# The Enhance subpanel's settings. App-wide, so they belong to the session
# rather than to any folder's row in the database.
_ENHANCE_SETTINGS_KEY = "enhance_settings"
# How the gallery search lays its results out (newest first, or banded by model +
# LoRA). The query itself is deliberately not saved — a search is something you
# are doing, not somewhere you were — but which way you like to read the answer
# is a preference, and re-picking it every launch is the kind of small friction
# that makes a control feel unfinished.
_SEARCH_SORT_KEY = "search_sort"
# How tall the user has dragged each prompt box, by param key — app-wide for the
# same reason, and restored before the first form is built (see __init__).
_PROMPT_HEIGHTS_KEY = "prompt_heights"


class OrigeneratorWindow(QMainWindow):
    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 parent=None, *, fun_time: FunTimeSession | None = None):
        super().__init__(parent)
        self._app_state = app_state
        self._fun_time = fun_time
        # Before anything below builds a param form: a prompt box reads its
        # height as it is constructed, and the view built a few lines down brings
        # its first one with it.
        PROMPT_HEIGHTS.restore(app_state.get(_PROMPT_HEIGHTS_KEY))
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
        if fun_time is not None:
            # A managed window of the hosting session: frameless so the client
            # area IS the rect Fun Time named (the Random Favs Browser's), and
            # in the topmost band where every managed window lives — Fun Time
            # decides who within the band is in front.
            self.setWindowFlags(
                self.windowFlags()
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            rect = fun_time.main_rect
            # Set here so the window opens near the right size, then pinned to
            # the exact DEVICE rect once it is shown (see showEvent): a scaled
            # process cannot say a second monitor's coordinates in Qt's space at
            # all (origenerator.win32.place_window_in_device_pixels).
            self.setGeometry(rect.x, rect.y, rect.width, rect.height)

        # The rect this window is pinned to once shown, or None standalone.
        self._device_rect = (
            (fun_time.main_rect.x, fun_time.main_rect.y,
             fun_time.main_rect.width, fun_time.main_rect.height)
            if fun_time is not None else None
        )

        # One unified view: the gallery, whose info pane now holds the editable
        # config tabs that used to be a separate Generate tab. A clicked
        # thumbnail, the re-roll "+", and the combine panel all feed it.
        self._gallery_view = GalleryView(db, client=client, fun_time=fun_time)
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
        # The same absence carried a batch of base re-renders. Fold the ones that
        # finished into the images they repair — before the first refresh builds
        # the tree, so a repaired image is already showing both its versions when
        # it is drawn — and drop the rest: the GPU is the user's again.
        fold_completed_base_renders(db)
        cancel_base_renders(db, client)
        # Reconnect to any generation left running by the previous session. A tab's
        # Generate is itself a re-roll, so every in-flight row is the gallery's to
        # re-adopt — the tabs restore their configs only, owning no jobs.
        self._gallery_view.reconnect_running_rerolls()

    def _restore_session(self):
        """Put the window back where it was — same monitor, size, and maximized
        state — and reopen the last session's config tabs, gallery folder, and
        selected generation.  Inside a Fun Time session the geometry is the
        session's to dictate, so the saved one is neither restored nor (see
        ``closeEvent``) overwritten."""
        if self._fun_time is None:
            self._restore_geometry()
        self._gallery_view.restore_config_tabs(self._app_state.get(_CONFIG_TABS_KEY))
        self._gallery_view.select_folder(self._app_state.get(_GALLERY_FOLDER_KEY))
        self._gallery_view.select_generation(self._app_state.get(_GALLERY_SELECTION_KEY))
        self._gallery_view.restore_combine_selection(self._app_state.get(_GALLERY_COMBINE_KEY))
        self._gallery_view.set_osr2_enabled(self._app_state.get(_OSR2_ENABLED_KEY))
        self._gallery_view.set_experiments_enabled(
            self._app_state.get(_EXPERIMENTS_ENABLED_KEY))
        self._gallery_view.set_audio_enabled(self._app_state.get(_AUDIO_ENABLED_KEY))
        self._gallery_view.set_mic_enabled(self._app_state.get(_MIC_ENABLED_KEY))
        self._gallery_view.set_enhance_settings(
            self._app_state.get(_ENHANCE_SETTINGS_KEY))
        self._gallery_view.set_search_sort(self._app_state.get(_SEARCH_SORT_KEY))

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

    def showEvent(self, event):
        """Pin the window to the DEVICE rect the session named.

        Qt has already placed it by then, in its own coordinates, which in a
        scaled process cannot name a point on a second monitor unambiguously
        (origenerator.win32.place_window_in_device_pixels says why).  So the
        rect is re-applied through Win32 every time the window is shown --
        cheap, and it survives a reparent or a flag change putting Qt's own
        geometry back.
        """
        super().showEvent(event)
        if self._device_rect is not None:
            place_window_in_device_pixels(int(self.winId()), *self._device_rect)

    def closeEvent(self, event):
        """Hand ComfyUI the background experiments for the coming absence and
        everything else the queue is still holding, then persist the session (open
        config tabs, gallery folder/selection) and the window geometry so the next
        launch reopens as it was."""
        for chore in (self._gallery_view.queue_experiments_for_absence,
                      self._gallery_view.queue_base_renders_for_absence,
                      # Last, so the batches above go with it: the queue holds
                      # work back for the sake of somebody watching, and there is
                      # about to be nobody watching.
                      self._gallery_view.flush_queue_to_server):
            # Each on its own, and none of them able to take the session down with
            # it. These are errands for a machine nobody is using; what the user
            # actually loses if the close breaks is everything below — the open
            # tabs, the folder they were in, the window's place on its monitor.
            # A typo in one of these chores ate exactly that, silently, for three
            # days (``gallery.BASE_RENDER_SOURCE``, which the package had never
            # exported), and the app looked fine the whole time because nothing
            # a closing window raises is ever shown to anyone.
            try:
                chore()
            except Exception as e:
                logger.warning("Close-time %s failed: %s", chore.__name__, e)
        self._app_state.set(_CONFIG_TABS_KEY, self._gallery_view.capture_config_tabs())
        self._app_state.set(_GALLERY_FOLDER_KEY, self._gallery_view.selected_folder())
        self._app_state.set(_GALLERY_SELECTION_KEY, self._gallery_view.selected_generation())
        self._app_state.set(_GALLERY_COMBINE_KEY, self._gallery_view.combine_selection())
        self._app_state.set(_OSR2_ENABLED_KEY, self._gallery_view.osr2_enabled())
        self._app_state.set(
            _EXPERIMENTS_ENABLED_KEY, self._gallery_view.experiments_enabled())
        self._app_state.set(_AUDIO_ENABLED_KEY, self._gallery_view.audio_enabled())
        self._app_state.set(_MIC_ENABLED_KEY, self._gallery_view.mic_enabled())
        self._app_state.set(
            _ENHANCE_SETTINGS_KEY, self._gallery_view.enhance_settings())
        self._app_state.set(_SEARCH_SORT_KEY, self._gallery_view.search_sort())
        self._app_state.set(_PROMPT_HEIGHTS_KEY, PROMPT_HEIGHTS.snapshot())
        if self._fun_time is None:
            # Hosted, the geometry is the session's to decide, so remembering
            # this launch's would overwrite the window the user actually sizes.
            self._app_state.set(
                _GEOMETRY_KEY,
                base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
            )
        self._app_state.save()
        super().closeEvent(event)
