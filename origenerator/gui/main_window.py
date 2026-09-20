from __future__ import annotations

import base64
import logging

from PyQt6.QtCore import QByteArray, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow

from origenerator import ui_scale
from origenerator.app_state import AppState
from origenerator.base_backfill import cancel_base_renders, fold_completed_base_renders
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import PROJECT_DIR
from origenerator.db import Database
from origenerator.experiments.background import cancel_experiments
from origenerator.fun_time_mode import FunTimeSession
from origenerator.gui.desktop_notices import DesktopNotices
from origenerator.gui.fun_time_bridge import FunTimeBridge
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.prompt_field import PROMPT_HEIGHTS
from origenerator.win32 import place_window_in_device_pixels

logger = logging.getLogger(__name__)

# Everything the session remembers about the view, as (its key in the state file,
# what the view is asked for it on the way out, what the view is told on the way
# back in). One list rather than three: a key used to be declared, then restored
# by a hand-written line, then saved by another twenty lines away, and a
# preference restored but never saved — or the reverse — failed silently and
# stayed that way. The pair is named as the view's own methods rather than by
# name, so a half-wired preference is an import error and the dead-code gate can
# still see who calls them.
#
# The keys are the state file's public surface and cannot change, "generate_tabs"
# included: it is from before the Generate and Gallery views merged, and a
# session saved then still opens. "osr2_enabled" is the same: it holds which of
# the four OSR2 control states the app was left in, and reads the True or False
# of the on/off switch it held before.
#
# The order is the restore order and is load-bearing: the tabs before the folder
# before the generation, each later one needing what the earlier ones put up.
SESSION_PREFS = (
    ("generate_tabs", GalleryView.capture_config_tabs, GalleryView.restore_config_tabs),
    ("gallery_folder", GalleryView.selected_folder, GalleryView.select_folder),
    ("gallery_selection", GalleryView.selected_generation, GalleryView.select_generation),
    ("gallery_combine", GalleryView.combine_selection, GalleryView.restore_combine_selection),
    ("osr2_enabled", GalleryView.osr2_state, GalleryView.restore_osr2_state),
    ("experiments_enabled", GalleryView.experiments_enabled, GalleryView.set_experiments_enabled),
    ("audio_enabled", GalleryView.audio_enabled, GalleryView.set_audio_enabled),
    # The mic switch. Absent from a session saved before it was persisted — and
    # from a first launch — which is the app's default of on (see set_mic_enabled).
    ("mic_enabled", GalleryView.mic_enabled, GalleryView.set_mic_enabled),
    # The Enhance subpanel's settings. App-wide, so they belong to the session
    # rather than to any folder's row in the database.
    ("enhance_settings", GalleryView.enhance_settings, GalleryView.set_enhance_settings),
    # How the gallery search lays its results out (newest first, or banded by
    # model + LoRA). The query itself is deliberately not saved — a search is
    # something you are doing, not somewhere you were — but which way you like to
    # read the answer is a preference, and re-picking it every launch is the kind
    # of small friction that makes a control feel unfinished.
    ("search_sort", GalleryView.search_sort, GalleryView.set_search_sort),
)

# The two the view does not own. Geometry is the window's own, and the prompt
# heights are a module-level store read before the first form is built (see
# __init__), so neither is a view getter and neither belongs in the table.
_GEOMETRY_KEY = "window_geometry"
_PROMPT_HEIGHTS_KEY = "prompt_heights"
_SWITCHES_THE_SESSION_OWNS = frozenset({"audio_enabled", "osr2_enabled", "mic_enabled"})


class OrigeneratorWindow(QMainWindow):
    handed_back = pyqtSignal()

    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 parent=None, *, fun_time: FunTimeSession | None = None):
        super().__init__(parent)
        self._app_state = app_state
        self._fun_time = fun_time
        # Before anything below builds a param form: a prompt field reads its
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
        # The rect this window is pinned to once shown, or None standalone.
        self._device_rect = None
        if fun_time is not None:
            self._wear_the_session(fun_time)

        # One unified view: the gallery, whose info pane now holds the editable
        # config tabs that used to be a separate Generate tab. A clicked
        # thumbnail, the re-roll "+", and the combine panel all feed it.
        self._gallery_view = GalleryView(db, client=client, fun_time=fun_time,
                                         prompt_heights=PROMPT_HEIGHTS)
        self.setCentralWidget(self._gallery_view)
        # Where a run that outlasted the user's attention reports itself: the
        # window's own icon, on a tray icon that lives as long as the app does.
        self._notices = DesktopNotices(self.windowIcon(), parent=self)
        self._gallery_view.run_ended.connect(self._notices.note)
        if fun_time is not None:
            # The session's channels: its verbs onto the region shows, the
            # paused flag over them, and the occupancy status back. Built here
            # rather than by the boot, which had to reach through this window
            # for the gallery to hand over. Parented to the window, so it lives
            # exactly as long as the app.
            FunTimeBridge(fun_time, self._gallery_view, parent=self)

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
        # alone, both ends of it: the rows a branch session would clear are the
        # live app's experiments, running in the ComfyUI they share.
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
        for key, _getter, setter in SESSION_PREFS:
            setter(self._gallery_view, self._app_state.get(key))

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

    def the_session_has_the_device(self, held: bool) -> None:
        """A Fun Time session running beside this window has the OSR2, or not."""
        self._gallery_view.osr2_control.the_session_has_it(held)

    def become_hosted(self, session: FunTimeSession) -> None:
        logger.info("Taken into a Fun Time session; the OSR2 and the appliance "
                    "switches are the session's from here")
        self._persist_session()
        self._found = (self.saveGeometry(), ui_scale.active_scale(), self.isMinimized())
        self._fun_time = session
        self._gallery_view.become_hosted(session)
        self.setWindowState(Qt.WindowState.WindowNoState)
        ui_scale.draw_at(ui_scale.hosted_scale())
        self._wear_the_session(session)
        self._bridge = FunTimeBridge(session, self._gallery_view, parent=self)
        self._bridge.released.connect(self.become_standalone)
        self.showMinimized()

    def become_standalone(self) -> None:
        logger.info("Handed back by the Fun Time session; standalone again")
        geometry, scale, minimized = self._found
        self._bridge.deleteLater()
        self._bridge = None
        self._fun_time = None
        self._gallery_view.become_standalone()
        self._gallery_view.set_mic_enabled(self._app_state.get("mic_enabled"))
        self.setWindowFlags(self.windowFlags()
                            & ~Qt.WindowType.FramelessWindowHint
                            & ~Qt.WindowType.WindowStaysOnTopHint)
        self._device_rect = None
        self.setWindowState(Qt.WindowState.WindowNoState)
        ui_scale.draw_at(scale)
        self.restoreGeometry(geometry)
        if minimized:
            self.showMinimized()
        else:
            self.show()
        self.handed_back.emit()

    def _wear_the_session(self, session: FunTimeSession) -> None:
        # A managed window of the hosting session: frameless so the client
        # area IS the rect Fun Time named (the Random Favs Browser's), and
        # in the topmost band where every managed window lives — Fun Time
        # decides who within the band is in front.
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        rect = session.main_rect
        # Set here so the window opens near the right size, then pinned to
        # the exact DEVICE rect once it is shown (see showEvent): a scaled
        # process cannot say a second monitor's coordinates in Qt's space at
        # all (origenerator.win32.place_window_in_device_pixels).
        self.setGeometry(rect.x, rect.y, rect.width, rect.height)
        self._device_rect = (rect.x, rect.y, rect.width, rect.height)

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
            # days (a name for the base-render source the gallery package had
            # never exported), and the app looked fine the whole time because nothing
            # a closing window raises is ever shown to anyone.
            try:
                chore()
            except Exception as e:
                logger.warning("Close-time %s failed: %s", chore.__name__, e)
        self._persist_session()
        super().closeEvent(event)

    def _persist_session(self) -> None:
        for key, getter, _setter in SESSION_PREFS:
            if self._fun_time is not None and key in _SWITCHES_THE_SESSION_OWNS:
                continue
            self._app_state.set(key, getter(self._gallery_view))
        self._app_state.set(_PROMPT_HEIGHTS_KEY, PROMPT_HEIGHTS.snapshot())
        if self._fun_time is None:
            # Hosted, the geometry is the session's to decide, so remembering
            # this launch's would overwrite the window the user actually sizes.
            self._app_state.set(
                _GEOMETRY_KEY,
                base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
            )
        self._app_state.save()
