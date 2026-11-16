from __future__ import annotations

import base64
import contextlib
import logging
from dataclasses import dataclass, replace
from operator import attrgetter

from app_support.loading_screen import MeetingPlace
from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow
from shared_ui.application import close_the_windows_it_opened
from shared_ui.foreground import bring_to_front
from shared_ui.hard_to_miss import sure
from shared_ui.preview import Preview, window_title

from origenerator import downtime, osr2, places_backfill, ui_scale
from origenerator.app_state import AppState
from origenerator.base_backfill import cancel_base_renders, fold_completed_base_renders
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.evolver_export import EvolverInbox
from origenerator.experiments.background import cancel_experiments
from origenerator.flick_finales import drop_finales_in_flight
from origenerator.fun_time_bridge import FunTimeBridge
from origenerator.fun_time_mode import WINDOW_TITLE, FunTimeSession, Rect
from origenerator.gui.app_title import AppTitle
from origenerator.gui.combine_controller import CombineController
from origenerator.gui.enhance_controller import EnhanceController
from origenerator.gui.gallery_search import GallerySearchController
from origenerator.gui.gallery_view import GalleryView, Shared
from origenerator.gui.generate_pane import GeneratePane
from origenerator.gui.headset_window import CAP_PX, HeadsetWindow
from origenerator.gui.osr2_driving import Osr2Driving
from origenerator.gui.panes import RememberedBorders
from origenerator.gui.prompt_field import PROMPT_HEIGHTS
from origenerator.gui.slideshow_director import SlideshowDirector
from origenerator.gui.taskbar_identity import TaskbarIdentity
from origenerator.gui.toasts import Toasts
from origenerator.gui.two_screens import TwoScreens
from origenerator.gui.window_monitor import GEOMETRY_KEY, the_window_on
from origenerator.win32 import (
    bring_back_into_sight,
    keep_out_of_sight,
    out_of_sight,
    place_window_in_device_pixels,
)

logger = logging.getLogger(__name__)



class OwnedBy:
    def __init__(self, owner, its_own) -> None:
        self._owner = owner
        self.its_own = its_own

    def __call__(self, view, *saved):
        return self.its_own(self._owner(view), *saved)


def _osr2(its_own) -> OwnedBy:
    return OwnedBy(attrgetter("osr2"), its_own)


def _generate_pane(its_own) -> OwnedBy:
    return OwnedBy(attrgetter("generate_pane"), its_own)


def _slideshows(its_own) -> OwnedBy:
    return OwnedBy(attrgetter("slideshows"), its_own)


def _combine(its_own) -> OwnedBy:
    return OwnedBy(attrgetter("combine"), its_own)


def _enhance(its_own) -> OwnedBy:
    return OwnedBy(attrgetter("enhance"), its_own)


def _search(its_own) -> OwnedBy:
    return OwnedBy(attrgetter("search"), its_own)


SESSION_UI_STATE = (
    ("generate_tabs", _generate_pane(GeneratePane.capture_state),
     _generate_pane(GeneratePane.restore_state)),
    ("toc_shapes", GalleryView.toc_shapes, GalleryView.set_toc_sides),
    ("open_folders", GalleryView.open_folders, GalleryView.set_open_folders),
    ("gallery_folder", GalleryView.selected_folder, GalleryView.select_folder),
    ("gallery_selection", GalleryView.selected_generation, GalleryView.select_generation),
    ("gallery_combine", _combine(CombineController.selection),
     _combine(CombineController.restore)),
    ("osr2_enabled", _osr2(Osr2Driving.state), _osr2(Osr2Driving.restore_state)),
    ("max_intensity", _osr2(Osr2Driving.max_intensity), _osr2(Osr2Driving.set_max_intensity)),
    ("motion", _osr2(Osr2Driving.motion_settings), _osr2(Osr2Driving.set_motion_settings)),
    ("experiments_enabled", GalleryView.experiments_enabled, GalleryView.set_experiments_enabled),
    ("audio_enabled", GalleryView.radio_enabled, GalleryView.set_radio_enabled),
    ("mic_enabled", GalleryView.mic_enabled, GalleryView.set_mic_enabled),
    ("enhance_settings", _enhance(EnhanceController.settings_json),
     _enhance(EnhanceController.restore_settings)),
    ("search_sort", _search(GallerySearchController.sort),
     _search(GallerySearchController.set_sort)),
    ("slideshows", _slideshows(SlideshowDirector.remembered),
     _slideshows(SlideshowDirector.remember)),
    ("session_slideshows", _slideshows(SlideshowDirector.remembered_regions),
     _slideshows(SlideshowDirector.remember_regions)),
    ("how_many", _generate_pane(GeneratePane.how_many),
     _generate_pane(GeneratePane.restore_how_many)),
    ("request_auto_generate", _generate_pane(GeneratePane.request_auto_generate),
     _generate_pane(GeneratePane.restore_request_auto_generate)),
)

_PROMPT_HEIGHTS_KEY = "prompt_heights"
_PANE_SIZES_KEY = "pane_sizes"
_CORE_ON_KEY = "core_on"
_KEYS_THE_SESSION_OWNS = frozenset(
    {"audio_enabled", "osr2_enabled", "mic_enabled", "max_intensity", "motion", "slideshows"})

_ONLY_CORE_SHOWS = frozenset({"generate_tabs"})

SESSION_PERSIST_INTERVAL_MS = 5_000

_THE_ROOMS_FLAGS = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint


def _run_on_its_own(chore) -> None:
    try:
        chore()
    except Exception as e:
        logger.warning("Close-time %s failed: %s", chore.__name__, e)


@dataclass(frozen=True)
class Launch:
    preview: Preview | None = None
    taskbar: TaskbarIdentity | None = None
    next_launch: MeetingPlace | None = None


class Core(QMainWindow):
    handed_back = Signal()

    def __init__(self, client: ComfyUIClient, db: Database, app_state: AppState,
                 *, fun_time: FunTimeSession | None = None, launch: Launch | None = None,
                 inbox: EvolverInbox | None = None):
        super().__init__()
        launch = launch or Launch()
        self._app_state = app_state
        self._next_launch = launch.next_launch
        self._fun_time = fun_time
        self._he_said_yes_to_closing = False
        self._taskbar = launch.taskbar
        preview = launch.preview

        PROMPT_HEIGHTS.restore(app_state.get(_PROMPT_HEIGHTS_KEY))
        self.setWindowTitle(WINDOW_TITLE if fun_time else window_title(WINDOW_TITLE, preview))
        self.setMinimumSize(600, 400)
        self._device_rect = None
        if fun_time is not None:
            self._wear_the_session(fun_time)

        self._sides = TwoScreens(self)
        self._sides.put_core_on(app_state.get(_CORE_ON_KEY))
        self._sides.switched.connect(self._fill_its_monitor)
        self._title = AppTitle(WINDOW_TITLE, self.windowIcon(), preview)
        self._title.hide()
        self._gallery_view = GalleryView(db, client=client, fun_time=fun_time,
                                         shared=Shared(prompt_heights=PROMPT_HEIGHTS, inbox=inbox,
                                                       device_waits_for_the_window=True,
                                                       two_screens=self._sides,
                                                       app_title=self._title))
        self.setCentralWidget(self._gallery_view)
        self._toasts = Toasts(self.windowIcon(), parent=self, shown_as=preview,
                                       video_in_front=self._gallery_view.video_in_front)
        self._gallery_view.run_ended.connect(self._toasts.note)
        self._bridge: FunTimeBridge | None = None
        if fun_time is not None:
            self._bridge = FunTimeBridge(fun_time, self._gallery_view, parent=self,
                                         core_ready=False)
            self._answer_the_crossings(self._bridge)
        self.hands_its_window_over: HeadsetWindow | None = None
        self._found: tuple[QByteArray, float, bool] | None = None
        self._borders = RememberedBorders(self)
        if fun_time is not None and fun_time.in_a_headset:
            self._hand_the_window_over(fun_time)

        quit_shortcut = QShortcut(QKeySequence("Ctrl+Alt+Q"), self)
        quit_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_shortcut.activated.connect(self.close)
        self._gallery_view.quit_asked.connect(self._close_if_sure)

        self._still_to_restore = _ONLY_CORE_SHOWS if fun_time is not None else frozenset()
        self._restore_session()
        self._persist_the_session_as_it_changes()
        if not is_branch_session():
            cancel_experiments(db, client)
            drop_finales_in_flight(db, client)
        fold_completed_base_renders(db)
        cancel_base_renders(db, client)
        places_backfill.fold_found_places(db, client, places_backfill.RECORD)
        if not is_branch_session():
            downtime.forget_work_left()
        self._gallery_view.reconnect_running_jobs()

    def _restore_session(self):
        if self._fun_time is None or self._fun_time.in_a_headset:
            self._restore_geometry()
        self._fill_its_monitor()
        for key, _getter, setter in SESSION_UI_STATE:
            if key not in self._still_to_restore:
                setter(self._gallery_view, self._app_state.get(key))
        self._borders.take(self._app_state.get(_PANE_SIZES_KEY))
        if self._fun_time is None:
            self._borders.put_back()

    def restore_what_only_core_shows(self) -> None:
        for key, _getter, setter in SESSION_UI_STATE:
            if key in self._still_to_restore:
                setter(self._gallery_view, self._app_state.get(key))
        self._still_to_restore = frozenset()

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
        blob = self._app_state.get(GEOMETRY_KEY)
        if not isinstance(blob, str):
            return
        with contextlib.suppress(ValueError):
            self.restoreGeometry(QByteArray(base64.b64decode(blob)))

    def _fill_its_monitor(self) -> None:
        monitor = self._sides.cores_monitor()
        if self._fun_time is not None or monitor is None:
            return
        shown = self.isVisible()
        self.setWindowState(self.windowState() & ~(Qt.WindowState.WindowMaximized
                                                   | Qt.WindowState.WindowFullScreen))
        if not self.windowFlags() & Qt.WindowType.FramelessWindowHint:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setGeometry(monitor.availableGeometry())
        self._title.show()
        if shown:
            self.show()

    def showEvent(self, event):
        super().showEvent(event)
        # Qt puts its own geometry back on a reparent or a window-flag change, so the rect goes on again through Win32 at every show.
        if self._device_rect is not None:
            place_window_in_device_pixels(int(self.winId()), *self._device_rect)
        if self._fun_time is None:
            self._sides.core_is_up.emit()

    def go_to_generation(self, prompt_id: str) -> None:
        if self._fun_time is None:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            self.show()
            bring_to_front(self)
        self._gallery_view.show_generation(prompt_id)

    def the_session_has_the_device(self, held: bool) -> None:
        self._gallery_view.osr2.control.the_session_has_it(held)

    def slideshow_showing_on(self) -> str | None:
        return self._gallery_view.slideshow_showing_on()

    def core_is_ready(self) -> None:
        if self._bridge is not None:
            self._bridge.core_is_ready()

    def become_hosted(self, session: FunTimeSession) -> None:
        logger.info("Taken into a Fun Time session; the OSR2 and the appliance "
                    "switches are the session's from here")
        self._persist_session()
        self._found = (self.saveGeometry(), ui_scale.active_scale(), self.isMinimized())
        self._fun_time = session
        if self._taskbar is not None and session.taskbar_identity:
            self._taskbar.join(session.taskbar_identity)
        self._title.hide()
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
        self.show()
        keep_out_of_sight(int(self.winId()))
        self.hands_its_window_over = HeadsetWindow(self, session, parent=self)

    def _answer_the_crossings(self, bridge: FunTimeBridge) -> None:
        bridge.hand_over_asked.connect(self._handed_to_a_headset)
        bridge.take_back_asked.connect(self._taken_back_to_the_monitors)

    def _handed_to_a_headset(self, frames_file, input_file) -> None:
        logger.info("A headset session has this window now; its frame goes to %s "
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
                    "publishing its frame and parks")
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
        self._fill_its_monitor()
        self.handed_back.emit()

    def _stand_where_found(self, geometry: QByteArray, scale: float, minimized: bool) -> None:
        with out_of_sight(int(self.winId())):
            self.setWindowFlag(_THE_ROOMS_FLAGS, False)
            self._device_rect = None
            ui_scale.draw_at(scale)
            self.showNormal()
            self.restoreGeometry(geometry)
            if minimized:
                self.showMinimized()

    def _wear_the_session(self, session: FunTimeSession) -> None:
        self._dress_for_the_room(session)
        if session.in_a_headset:
            self._fill_the_frame_cap()
        else:
            self._sit_at_the_sessions_rect(session.main_rect)

    def _dress_for_the_room(self, session: FunTimeSession) -> None:
        self.setWindowFlag(_THE_ROOMS_FLAGS, not session.in_a_headset)

    def _wear_the_desktop_geometry(self) -> None:
        self.setWindowState(Qt.WindowState.WindowNoState)
        self._device_rect = None
        if self._found is None:
            self._restore_geometry()
        else:
            self.restoreGeometry(self._found[0])
        self._fill_the_frame_cap()

    def _fill_the_frame_cap(self) -> None:
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        grow = CAP_PX / max(width, height)
        self.resize(round(width * grow), round(height * grow))

    def _sit_at_the_sessions_rect(self, rect: Rect) -> None:
        self.setGeometry(rect.x, rect.y, rect.width, rect.height)
        self._device_rect = (rect.x, rect.y, rect.width, rect.height)

    def closeEvent(self, event):
        if event.spontaneous() and not self._sure_to_close():
            event.ignore()
            return
        _run_on_its_own(self._leave_work_for_while_closed)
        self._persist_session()
        self._gallery_view.close()
        close_the_windows_it_opened(self)
        super().closeEvent(event)
        _run_on_its_own(self._remind_to_turn_off_the_osr2)

    def _remind_to_turn_off_the_osr2(self) -> None:
        if self._he_said_yes_to_closing:
            osr2.ask_for_the_turn_off_reminder()

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
        self._he_said_yes_to_closing = sure(
            self, "Close Origenerator", "Are you sure you want to close Origenerator?")
        return self._he_said_yes_to_closing

    def _persist_session(self) -> None:
        for key, getter, _setter in SESSION_UI_STATE:
            if self._fun_time is not None and key in _KEYS_THE_SESSION_OWNS:
                continue
            if key in self._still_to_restore:
                continue
            self._app_state.set(key, getter(self._gallery_view))
        self._app_state.set(_PROMPT_HEIGHTS_KEY, PROMPT_HEIGHTS.snapshot())
        if self._fun_time is None:
            self._borders.keep_where_they_are()
        self._app_state.set(_PANE_SIZES_KEY, self._borders.sizes())
        self._app_state.set(_CORE_ON_KEY, self._sides.core_on())
        if self._fun_time is None and self.isVisible():
            self._app_state.set(
                GEOMETRY_KEY,
                base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
            )
            if self._next_launch is not None:
                self._next_launch.say_where_the_app_comes_up(the_window_on(self.screen()))
        self._app_state.save()
