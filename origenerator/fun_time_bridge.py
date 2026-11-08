from __future__ import annotations

import logging
import time
from pathlib import Path

from funestra.file_channel import (
    append_command,
    consume_command_file,
    publish_whole,
    read_paused_state,
)
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

from origenerator.config import RADIO_DIR
from origenerator.fun_time_mode import (
    CLOSE_SLIDESHOW,
    CLOSE_SLIDESHOWS,
    FILTER_ENHANCED,
    GO_TO,
    HAND_OVER,
    LOCK_HELD,
    OPEN_SLIDESHOW,
    RELEASE,
    REQUEST_CLOSED,
    REQUEST_OPEN,
    SAID_AT,
    SAY,
    SHAPES,
    TAKE_BACK,
    TRASH_FILE,
    FunTimeSession,
)
from origenerator.osr2_controls_commands import shape_press, shape_spoken_to, spelled_for
from origenerator.radio import deal_to_the_funestras
from origenerator.slideshow_buttons import (
    HUD_FACTS,
    ORIGENERATOR_MODE,
    PRESSES_ABOUT_THE_SLIDE,
    answer,
    origenerator_mode_on,
)

logger = logging.getLogger(__name__)

_POLL_MS = 150


def ask_for_omnipause(dashboard_cmd_file) -> None:
    append_command(dashboard_cmd_file, "omnipause_toggle")


def ask_for_the_funestra(dashboard_cmd_file, shape: str) -> None:
    append_command(dashboard_cmd_file, origenerator_mode_on(shape))


def ask_for_origenerator_mode(dashboard_cmd_file) -> None:
    if dashboard_cmd_file is not None:
        append_command(dashboard_cmd_file, ORIGENERATOR_MODE)


def tell_of_a_lock(dashboard_cmd_file, shape: str, file) -> bool:
    return dashboard_cmd_file is not None and append_command(
        dashboard_cmd_file, f"{spelled_for(shape, LOCK_HELD)}|{file}")


def _split_argument(line: str) -> tuple[str, str, str]:
    cuts = [line.find(mark) for mark in ":|" if mark in line]
    if not cuts:
        return line, "", ""
    cut = min(cuts)
    return line[:cut], line[cut], line[cut + 1:]


def _without_when_said(said: str) -> tuple[str, float | None]:
    words, marked, stamp = said.rpartition(SAID_AT)
    try:
        said_at_epoch_seconds = float(stamp) if marked else None
    except ValueError:
        said_at_epoch_seconds = None
    if said_at_epoch_seconds is None:
        return said, None
    return words, time.monotonic() - (time.time() - said_at_epoch_seconds)


class FunTimeBridge(QObject):
    released = pyqtSignal()
    hand_over_asked = pyqtSignal(Path, Path)
    take_back_asked = pyqtSignal()

    def __init__(self, session: FunTimeSession, gallery, parent=None, *, radio_dir=RADIO_DIR):
        super().__init__(parent)
        self._session = session
        self._radio_dir = radio_dir
        self._radio: list[Path] | None = None
        self._gallery = gallery
        self._paused = False
        self._published = False
        self._session_verbs = {
            CLOSE_SLIDESHOWS: self._close_the_slideshows,
            FILTER_ENHANCED: self._filter_enhanced,
            RELEASE: self._release,
            TAKE_BACK: self.take_back_asked.emit,
        }
        self._shape_verbs = {
            OPEN_SLIDESHOW: self._gallery.fill_the_region,
            CLOSE_SLIDESHOW: self._close_the_slideshow,
        }
        self._request_shape: str | None = None
        self._released = False
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.take_the_radio_back)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._drain_commands()
        if self._released:
            return
        self._deal_the_radio_once()
        self._apply_paused()
        self._publish_status()

    def _deal_the_radio_once(self) -> None:
        if self._radio is not None:
            return
        playlists = {shape: channel.playlist for shape in SHAPES
                     if (channel := self._session.funestra(shape)) is not None}
        self._radio = deal_to_the_funestras(playlists, videos_dir=self._radio_dir)

    def take_the_radio_back(self) -> None:
        for path in self._radio or ():
            try:
                path.unlink(missing_ok=True)
            except OSError as refused:
                logger.warning("Could not take back the radio dealt in %s: %s", path, refused)
        self._radio = []

    def _drain_commands(self) -> None:
        if self._session.command_file is None:
            return
        for verb in consume_command_file(self._session.command_file, logger=logger,
                                         uppercase=False):
            if self._released:
                return
            self._apply(verb.strip())

    def _apply(self, line: str) -> None:
        if not line:
            return
        keyword, marker, argument = _split_argument(line)
        said_at = None
        if marker == ":":
            argument, said_at = _without_when_said(argument)
        elif not marker:
            keyword, said_at = _without_when_said(keyword)
        keyword = keyword.upper()
        if keyword == HAND_OVER and marker == "|":
            frames, _, taken = argument.partition("|")
            self.hand_over_asked.emit(Path(frames), Path(taken))
            return
        if not marker and keyword in self._session_verbs:
            self._session_verbs[keyword]()
            return
        if keyword == GO_TO and marker == "|":
            self._gallery.go_to_file(argument)
            return
        if keyword == SAY.upper() and marker == ":":
            self._gallery.run_spoken_command(argument, said_at)
            return
        if keyword == TRASH_FILE and marker == "|":
            self._gallery.trash_file(argument)
            return
        self._apply_to_a_shape(line, keyword, marker, argument, said_at)

    def _apply_to_a_shape(self, line: str, keyword: str, marker: str, argument: str, said_at: float | None) -> None:
        shape = shape_spoken_to(keyword, SHAPES)
        if shape is None:
            logger.warning("Unknown Fun Time verb dropped: %s", line)
            return
        action, argument = shape_press(shape, keyword.lower(), argument)
        if not marker and action in self._shape_verbs:
            self._shape_verbs[action](shape)
            return
        if action in HUD_FACTS:
            self._gallery.tell_the_hud(shape, action, argument)
            return
        if action == SAY and marker == ":":
            self._run_what_was_said(shape, argument, said_at)
            return
        self._apply_shape(shape, action, argument, line, said_at)

    def _run_what_was_said(self, shape: str, words: str, said_at: float | None) -> None:
        was_taking_a_request = self._gallery.taking_a_request()
        self._gallery.run_spoken_command(f"{shape} {words}", said_at)
        taking_a_request = self._gallery.taking_a_request()
        if taking_a_request == was_taking_a_request:
            return
        self._request_shape = shape if taking_a_request else None
        self._tell_the_room(spelled_for(shape, REQUEST_OPEN if taking_a_request
                                        else REQUEST_CLOSED))

    def _close_the_slideshow(self, shape: str) -> None:
        self._drop_the_request_said_to(shape)
        self._gallery.close_the_slideshow(shape)

    def _close_the_slideshows(self) -> None:
        self._drop_the_request_said_to(self._request_shape)
        self._gallery.close_the_slideshows()

    def _drop_the_request_said_to(self, shape: str | None) -> None:
        if shape is None or shape != self._request_shape:
            return
        self._gallery.drop_the_request()
        self._request_shape = None
        self._tell_the_room(spelled_for(shape, REQUEST_CLOSED))

    def _tell_the_room(self, line: str) -> None:
        if self._session.dashboard_cmd_file is not None:
            append_command(self._session.dashboard_cmd_file, line)

    def _release(self) -> None:
        self._drop_the_request_said_to(self._request_shape)
        self._released = True
        self._timer.stop()
        self.take_the_radio_back()
        self.released.emit()

    def _filter_enhanced(self) -> None:
        slideshows = [slideshow for slideshow in map(self._gallery.region_slideshow, SHAPES)
                      if slideshow is not None]
        enhanced_only = not any(slideshow.hud_enhanced_mode for slideshow in slideshows)
        for slideshow in slideshows:
            slideshow.set_enhanced_mode(enhanced_only)

    def _apply_shape(self, shape: str, action: str, argument: str, line: str,
                    said_at: float | None) -> None:
        slideshow = self._gallery.region_slideshow(shape)
        if slideshow is None:
            return
        if action in PRESSES_ABOUT_THE_SLIDE:
            slideshow.back_to_what_was_said_over(said_at)
        if not answer(slideshow, action, argument):
            logger.warning("Unanswered press for the %s slideshow dropped: %s", shape, line)

    def _apply_paused(self) -> None:
        if self._session.paused_file is None:
            return
        paused = read_paused_state(self._session.paused_file, logger=logger)
        if paused == self._paused:
            return
        self._paused = paused
        self._gallery.set_room_paused(paused)

    READY = "ready=1"

    def _publish_status(self) -> None:
        if self._session.status_file is None:
            return
        if self._published and self._session.status_file.exists():
            return
        self._published = publish_whole(self._session.status_file,
                                        self.READY + "\n")
