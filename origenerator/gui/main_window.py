from __future__ import annotations

import base64
import logging
from dataclasses import replace

from app_support.loading_screen import MeetingPlace
from PyQt6.QtCore import QByteArray, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from shared_ui.foreground import bring_to_front
from shared_ui.preview import Preview, window_title

from origenerator import downtime, places_backfill, ui_scale
from origenerator.app_state import AppState
from origenerator.base_backfill import cancel_base_renders, fold_completed_base_renders
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.experiments.background import cancel_experiments
from origenerator.fun_time_bridge import FunTimeBridge
from origenerator.fun_time_mode import WINDOW_TITLE, FunTimeSession, Rect
from origenerator.gui.desktop_notices import DesktopNotices
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.hard_to_miss import hard_to_miss
from origenerator.gui.headset_window import CAP_PX, HeadsetWindow
from origenerator.gui.panes import RememberedBorders
from origenerator.gui.prompt_field import PROMPT_HEIGHTS
from origenerator.gui.taskbar_identity import TaskbarIdentity
from origenerator.gui.window_monitor import GEOMETRY_KEY, the_window_on
from origenerator.win32 import (
    bring_back_into_sight,
    keep_out_of_sight,
    out_of_sight,
    place_window_in_device_pixels,
)

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
# session saved then still opens. "osr2_enabled" is the same: it holds whether
# the OSR2 switch was left driving or parked, and reads the True or False the
# switch held before it had four states, and the retracted and control off of
# those four, as parked.
#
# The order is the restore order and is load-bearing: the tabs before the folder
# before the generation, each later one needing what the earlier ones put up.
SESSION_UI_STATE = (
    ("generate_tabs", GalleryView.capture_config_tabs, GalleryView.restore_config_tabs),
    ("toc_sides", GalleryView.toc_sides, GalleryView.set_toc_sides),
    ("open_folders", GalleryView.open_folders, GalleryView.set_open_folders),
    ("gallery_folder", GalleryView.selected_folder, GalleryView.select_folder),
    ("gallery_selection", GalleryView.selected_generation, GalleryView.select_generation),
    ("gallery_combine", GalleryView.combine_selection, GalleryView.restore_combine_selection),
    ("osr2_enabled", GalleryView.osr2_state, GalleryView.restore_osr2_state),
    ("max_intensity", GalleryView.max_intensity, GalleryView.set_max_intensity),
    ("motion", GalleryView.motion_settings, GalleryView.set_motion_settings),
    ("experiments_enabled", GalleryView.experiments_enabled, GalleryView.set_experiments_enabled),
    # Origenerator Radio's switch, under the name it was saved by before it was
    # the radio: a saved session keeps the word it was written with.
    ("audio_enabled", GalleryView.radio_enabled, GalleryView.set_radio_enabled),
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
    ("slideshows", GalleryView.remembered_slideshows, GalleryView.remember_slideshows),
    ("how_many", GalleryView.how_many, GalleryView.set_how_many),
)

# The three the view does not own. Geometry and where each border was dragged
# are the window's own, and the prompt heights are a module-level store read
# before the first form is built (see __init__), so none is a view getter and
# none belongs in the table.
_PROMPT_HEIGHTS_KEY = "prompt_heights"
_PANE_SIZES_KEY = "pane_sizes"
_KEYS_THE_SESSION_OWNS = frozenset(
    {"audio_enabled", "osr2_enabled", "mic_enabled", "max_intensity", "motion", "slideshows"})

SESSION_PERSIST_INTERVAL_MS = 5_000


def _run_on_its_own(chore) -> None:
    try:
        chore()
    except Exception as e:
        logger.warning("Close-time %s failed: %s", chore.__name__, e)


class OrigeneratorWindow(QMainWindow):
    handed_back = pyqtSignal()

    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 parent=None, *, fun_time: FunTimeSession | None = None,
                 preview: Preview | None = None, taskbar: TaskbarIdentity | None = None,
                 next_launch: MeetingPlace | None = None):
        super().__init__(parent)
        self._app_state = app_state
        self._next_launch = next_launch
        self._fun_time = fun_time
        self._taskbar = taskbar

        # Before anything below builds a param form: a prompt field reads its
        # height as it is constructed, and the view built a few lines down brings
        # its first one with it.
        PROMPT_HEIGHTS.restore(app_state.get(_PROMPT_HEIGHTS_KEY))
        self.setWindowTitle(WINDOW_TITLE if fun_time else window_title(WINDOW_TITLE, preview))
        # A small floor (not the old 1000x700) so a tiling window manager can snap
        # the window into a monitor third (~853px) or a portrait-monitor half
        # (~720px) — Qt maps this straight to the window's min track size. The
        # gallery's own pane floors keep content readable at those slot sizes; only
        # a manual drag below that compresses it.
        self.setMinimumSize(600, 400)
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
        self._notices = DesktopNotices(self.windowIcon(), parent=self, shown_as=preview,
                                       video_in_front=self._gallery_view.video_in_front)
        self._gallery_view.run_ended.connect(self._notices.note)
        if fun_time is not None:
            # The session's channels: its verbs onto the region slideshows, the
            # paused flag over them, and the occupancy status back. Built here
            # rather than by the boot, which had to reach through this window
            # for the gallery to hand over. Parented to the window, so it lives
            # exactly as long as the app.
            self._answer_the_crossings(
                FunTimeBridge(fun_time, self._gallery_view, parent=self))
        self.hands_its_window_over: HeadsetWindow | None = None
        self._found: tuple[QByteArray, float, bool] | None = None
        self._borders = RememberedBorders(self)
        if fun_time is not None and fun_time.in_a_headset:
            self._hand_the_window_over(fun_time)

        quit_shortcut = QShortcut(QKeySequence("Ctrl+Alt+Q"), self)
        quit_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_shortcut.activated.connect(self._close_if_sure)

        self._restore_session()
        self._persist_the_session_as_it_changes()
        # Background experiments belong to the closed app, so the ones the last
        # absence left in ComfyUI's queue are dropped before anything is adopted:
        # an open app never has one competing for the GPU. The production app's
        # alone, both ends of it: the rows a branch session would clear are the
        # production app's experiments, running in the ComfyUI they share.
        if not is_branch_session():
            cancel_experiments(db, client)
        # The same absence carried a batch of base re-renders. Fold the ones that
        # finished into the images they repair — before the first refresh builds
        # the tree, so a repaired image is already showing both its versions when
        # it is drawn — and drop the rest: the GPU is the user's again.
        fold_completed_base_renders(db)
        cancel_base_renders(db, client)
        places_backfill.fold_found_places(db, client, places_backfill.RECORD)
        if not is_branch_session():
            downtime.forget_work_left()
        # Reconnect to any generation left running by the previous session. A tab's
        # Generate is itself a re-roll, so every in-flight row is the gallery's to
        # re-adopt — the tabs restore their configs only, owning no jobs.
        self._gallery_view.reconnect_running_jobs()

    def _restore_session(self):
        """Put the window back where it was — same monitor, size, and maximized
        state — and reopen the last session's config tabs, gallery folder, and
        selected generation.  Inside a Fun Time session the geometry is the
        session's to dictate, so the saved one is neither restored nor (see
        ``closeEvent``) overwritten -- except in a headset, which names no rect."""
        if self._fun_time is None or self._fun_time.in_a_headset:
            self._restore_geometry()
        for key, _getter, setter in SESSION_UI_STATE:
            setter(self._gallery_view, self._app_state.get(key))
        self._borders.take(self._app_state.get(_PANE_SIZES_KEY))
        if self._fun_time is None:
            self._borders.put_back()

    def _persist_the_session_as_it_changes(self) -> None:
        saver = QTimer(self)
        saver.setInterval(SESSION_PERSIST_INTERVAL_MS)
        saver.timeout.connect(self._persist_session_or_try_again_next_time)
        saver.start()

    def _persist_session_or_try_again_next_time(self) -> None:
        try:
            self._persist_session()
        except Exception as e:
            logger.warning("Could not save the session; trying again shortly: %s", e)

    def _restore_geometry(self):
        """Reapply the saved window geometry: screen, size, and maximized state.

        Qt's ``saveGeometry`` blob is stored base64-encoded in the JSON state.
        A missing or corrupt value just leaves the window at its default size.
        """
        blob = self._app_state.get(GEOMETRY_KEY)
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

    def go_to_generation(self, prompt_id: str) -> None:
        """Put a generation in front of the user, from outside this window.

        What a clicked notification comes to (:mod:`origenerator.app_link`).
        Standalone that means this window over whatever they had moved on to;
        hosted, the window is the session's to show and taking the foreground
        for it would put it over the room instead, so the gallery asks the room
        for it, as it does for a lock in the room.
        """
        if self._fun_time is None:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            self.show()
            bring_to_front(self)
        self._gallery_view.show_generation(prompt_id)

    def the_session_has_the_device(self, held: bool) -> None:
        """A Fun Time session running beside this window has the OSR2, or not."""
        self._gallery_view.osr2_control.the_session_has_it(held)

    def shows_a_slideshow(self) -> bool:
        return self._gallery_view.shows_a_slideshow()

    def become_hosted(self, session: FunTimeSession) -> None:
        logger.info("Taken into a Fun Time session; the OSR2 and the appliance "
                    "switches are the session's from here")
        self._persist_session()
        self._found = (self.saveGeometry(), ui_scale.active_scale(), self.isMinimized())
        self._fun_time = session
        if self._taskbar is not None and session.taskbar_identity:
            self._taskbar.join(session.taskbar_identity)
        self._gallery_view.become_hosted(session)
        self.setWindowState(Qt.WindowState.WindowNoState)
        ui_scale.draw_at(ui_scale.room_scale(in_a_headset=session.in_a_headset))
        self._wear_the_session(session)
        self._bridge = FunTimeBridge(session, self._gallery_view, parent=self)
        self._bridge.released.connect(self.become_standalone)
        self._answer_the_crossings(self._bridge)
        if session.in_a_headset:
            self._hand_the_window_over(session)
        else:
            self.showMinimized()

    def _hand_the_window_over(self, session: FunTimeSession) -> None:
        """Publish this window's picture for a room in the headset, which has no
        monitor to put it on.  Shown, because Qt draws nothing for a window
        Windows has unmapped, and out of sight, because he is not in front of
        it."""
        self.show()
        keep_out_of_sight(int(self.winId()))
        self.hands_its_window_over = HeadsetWindow(self, session, parent=self)

    def _answer_the_crossings(self, bridge: FunTimeBridge) -> None:
        bridge.hand_over_asked.connect(self._handed_to_a_headset)
        bridge.take_back_asked.connect(self._taken_back_to_the_monitors)

    def _handed_to_a_headset(self, frames_file, input_file) -> None:
        logger.info("A headset session has this window now; its picture goes to %s "
                    "and its presses come from %s", frames_file, input_file)
        self._take_the_window_back()
        self._fun_time = replace(
            self._fun_time, frames_file=frames_file, input_file=input_file)
        ui_scale.draw_at(ui_scale.room_scale(in_a_headset=True))
        self._gallery_view.wear_the_room(self._fun_time)
        self._dress_for_the_room(self._fun_time)
        self._wear_the_desktop_geometry()
        self._hand_the_window_over(self._fun_time)

    def _taken_back_to_the_monitors(self) -> None:
        logger.info("A session on the monitors has this window now; it stops "
                    "publishing its picture and parks")
        self._take_the_window_back()
        self._fun_time = replace(self._fun_time, frames_file=None, input_file=None)
        ui_scale.draw_at(ui_scale.room_scale(in_a_headset=False))
        self._gallery_view.wear_the_room(self._fun_time)
        self._dress_for_the_room(self._fun_time)
        self._sit_at_the_sessions_rect(self._fun_time.main_rect)
        self.showMinimized()

    def _take_the_window_back(self) -> None:
        if self.hands_its_window_over is not None:
            bring_back_into_sight(int(self.winId()))
            self.hands_its_window_over.close()
            self.hands_its_window_over.deleteLater()
            self.hands_its_window_over = None

    def become_standalone(self) -> None:
        logger.info("Handed back by the Fun Time session; standalone again")
        self._take_the_window_back()
        self._bridge.deleteLater()
        self._bridge = None
        self._fun_time = None
        if self._taskbar is not None:
            self._taskbar.leave()
        self._gallery_view.become_standalone()
        self._borders.put_back()
        self._gallery_view.set_mic_enabled(self._app_state.get("mic_enabled"))
        self._stand_where_found(*self._found)
        self.handed_back.emit()

    def _stand_where_found(self, geometry: QByteArray, scale: float, minimized: bool) -> None:
        with out_of_sight(int(self.winId())):
            self.setWindowFlags(self.windowFlags()
                                & ~Qt.WindowType.FramelessWindowHint
                                & ~Qt.WindowType.WindowStaysOnTopHint)
            self._device_rect = None
            ui_scale.draw_at(scale)
            self.showNormal()
            self.restoreGeometry(geometry)
            if minimized:
                self.showMinimized()

    def _wear_the_session(self, session: FunTimeSession) -> None:
        # A managed window of the hosting session: frameless so the client
        # area IS the rect Fun Time named (the Random Favs Browser's), and
        # in the topmost band where every managed window lives — Fun Time
        # decides who within the band is in front.
        self._dress_for_the_room(session)
        if session.in_a_headset:
            self._fill_the_pictures_cap()
        else:
            self._sit_at_the_sessions_rect(session.main_rect)

    def _dress_for_the_room(self, session: FunTimeSession) -> None:
        managed = (Qt.WindowType.FramelessWindowHint
                   | Qt.WindowType.WindowStaysOnTopHint)
        flags = self.windowFlags()
        self.setWindowFlags(flags & ~managed if session.in_a_headset
                            else flags | managed)

    def _wear_the_desktop_geometry(self) -> None:
        self.setWindowState(Qt.WindowState.WindowNoState)
        self._device_rect = None
        if self._found is None:
            self._restore_geometry()
        else:
            self.restoreGeometry(self._found[0])
        self._fill_the_pictures_cap()

    def _fill_the_pictures_cap(self) -> None:
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        grow = CAP_PX / max(width, height)
        self.resize(round(width * grow), round(height * grow))

    def _sit_at_the_sessions_rect(self, rect: Rect) -> None:
        # Set here so the window opens near the right size, then pinned to
        # the exact DEVICE rect once it is shown (see showEvent): a scaled
        # process cannot say a second monitor's coordinates in Qt's space at
        # all (origenerator.win32.place_window_in_device_pixels).
        self.setGeometry(rect.x, rect.y, rect.width, rect.height)
        self._device_rect = (rect.x, rect.y, rect.width, rect.height)

    def closeEvent(self, event):
        if event.spontaneous() and not self._sure_to_close():
            event.ignore()
            return
        _run_on_its_own(self._leave_work_for_while_closed)
        self._persist_session()
        self._gallery_view.close()
        super().closeEvent(event)

    def hand_comfyui_what_runs_while_closed(self) -> None:
        _run_on_its_own(self._gallery_view.flush_queue_to_server)

    def _leave_work_for_while_closed(self) -> None:
        if not is_branch_session():
            downtime.leave_work_for_while_closed()

    def _close_if_sure(self) -> None:
        if self._sure_to_close():
            self.close()

    def _sure_to_close(self) -> bool:
        if self._fun_time is not None:
            return True
        with hard_to_miss(self):
            return QMessageBox.question(
                self, "Close Origenerator", "Are you sure you want to close Origenerator?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes

    def _persist_session(self) -> None:
        for key, getter, _setter in SESSION_UI_STATE:
            if self._fun_time is not None and key in _KEYS_THE_SESSION_OWNS:
                continue
            self._app_state.set(key, getter(self._gallery_view))
        self._app_state.set(_PROMPT_HEIGHTS_KEY, PROMPT_HEIGHTS.snapshot())
        if self._fun_time is None:
            self._borders.keep_where_they_are()
        self._app_state.set(_PANE_SIZES_KEY, self._borders.sizes())
        if self._fun_time is None and self.isVisible():
            # Hosted, the geometry is the session's to decide, so remembering
            # this launch's would overwrite the window the user actually sizes.
            self._app_state.set(
                GEOMETRY_KEY,
                base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
            )
            if self._next_launch is not None:
                self._next_launch.say_where_the_app_comes_up(the_window_on(self.screen()))
        self._app_state.save()
