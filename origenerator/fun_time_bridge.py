"""Fun Time's hands on a hosted Origenerator: the file channels, polled.

Fun Time drives its Satellite Funestras through a command file, a paused flag
and a status file (``funestra.file_channel`` / ``funestra.status``); a
hosted Origenerator answers the same idioms so the session reaches the region
slideshows the way it reaches the Funestras:

* ``PORTRAIT_NEXT`` steps whatever holds the portrait region the way ``NEXT``
  steps the Portrait Funestra — same for ``PREV``/``TRASH``/``LOCK``/``RESET``
  and the landscape side.  ``PORTRAIT_OPEN_SLIDESHOW`` fills that region (its
  Funestra switching INTO origenerator mode), ``PORTRAIT_CLOSE_SLIDESHOW``
  clears it again and ``CLOSE_SLIDESHOWS`` clears both;
  ``FILTER_ENHANCED`` flips the enhanced-only switch a slideshow's HUD and the
  session's console both carry; ``GO_TO|<file>`` puts the generation a file
  is a copy of in front of him, asking the room for this window's place;
  ``RELEASE`` gives a taken-over window back to standalone.  Every line it
  answers is declared in :mod:`origenerator.fun_time_mode`, which publishes them.
* The paused flag freezes the slideshows the way it freezes the Funestras, so
  OmniPause is one write here too — held by the gallery, not just edged onto
  the open slideshows, so a slideshow opened mid-pause opens frozen.
* The status file says which regions are occupied (and by what) — a readout
  for the hosting session's diagnostics.
* A click on a slideshow asks the room for OmniPause (:func:`ask_for_omnipause`) on
  the dashboard channel, where a Funestra's click on what it shows asks for it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from funestra.file_channel import (
    append_command,
    consume_command_file,
    publish_whole,
    read_paused_state,
)
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

from origenerator.config import RADIO_DIR
from origenerator.console_commands import side_press, side_spoken_to, spelled_for
from origenerator.fun_time_mode import (
    CLOSE_SLIDESHOW,
    CLOSE_SLIDESHOWS,
    FILTER_ENHANCED,
    GO_TO,
    HAND_OVER,
    OPEN_SLIDESHOW,
    RELEASE,
    REQUEST_CLOSED,
    REQUEST_OPEN,
    SAY,
    SIDES,
    TAKE_BACK,
    FunTimeSession,
)
from origenerator.radio import deal_to_the_funestras
from origenerator.slideshow_buttons import (
    ORIGENERATOR_MODE,
    PANEL_PLACES,
    answer,
    origenerator_mode_on,
)

logger = logging.getLogger(__name__)

_POLL_MS = 150


def ask_for_omnipause(dashboard_cmd_file) -> None:
    append_command(dashboard_cmd_file, "omnipause_toggle")


def ask_for_the_funestra(dashboard_cmd_file, side: str) -> None:
    append_command(dashboard_cmd_file, origenerator_mode_on(side))


def ask_for_origenerator_mode(dashboard_cmd_file) -> None:
    """Ask the room to show this app — the mode its own HUD button asks for.

    The session parks this window under the players in video mode, so anything
    that has to be seen here (a clicked notification, arriving from outside the
    room entirely) has to ask for the mode before it shows anything. An older
    session names no channel to ask on, and there the asking is simply skipped.
    """
    if dashboard_cmd_file is not None:
        append_command(dashboard_cmd_file, ORIGENERATOR_MODE)


def _split_argument(line: str) -> tuple[str, str, str]:
    """A verb, its marker, and what it carries: the words of a spoken phrase
    after a ":", the path of a thumbnail after a "|" — whichever comes first,
    since a Windows path carries a colon of its own."""
    cuts = [line.find(mark) for mark in ":|" if mark in line]
    if not cuts:
        return line, "", ""
    cut = min(cuts)
    return line[:cut], line[cut], line[cut + 1:]


class FunTimeBridge(QObject):
    """Polls the session's channels and routes them onto the gallery's slideshows."""

    released = pyqtSignal()
    hand_over_asked = pyqtSignal(Path, Path)  # the frames file, the input file
    take_back_asked = pyqtSignal()

    def __init__(self, session: FunTimeSession, gallery, parent=None, *, radio_dir=RADIO_DIR):
        super().__init__(parent)
        self._session = session
        self._radio_dir = radio_dir
        # The radio files dealt to the session's Funestras, None until dealt.
        self._radio: list[Path] | None = None
        self._gallery = gallery
        self._paused = False
        self._published = False
        # The verbs about the session's slideshows as a whole, rather than one side's.
        self._session_verbs = {
            CLOSE_SLIDESHOWS: self._close_the_slideshows,
            FILTER_ENHANCED: self._filter_enhanced,
            RELEASE: self._release,
            TAKE_BACK: self.take_back_asked.emit,
        }
        self._side_verbs = {
            OPEN_SLIDESHOW: lambda side: self._gallery.fill_the_region(side),
            CLOSE_SLIDESHOW: self._close_the_slideshow,
        }
        self._request_side: str | None = None
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

    # --- Origenerator Radio --------------------------------------------------

    def _deal_the_radio_once(self) -> None:
        """Deal each Funestra the session handed over its own stations, the
        moment this app is up: they play on out of earshot from then, so an
        image tunes in wherever its station has got to."""
        if self._radio is not None:
            return
        playlists = {side: channel.playlist for side in SIDES
                     if (channel := self._session.funestra(side)) is not None}
        self._radio = deal_to_the_funestras(playlists, clips_dir=self._radio_dir)

    def take_the_radio_back(self) -> None:
        """Silence the stations dealt to the session's Funestras: this app is
        going, and a radio with nothing of this app's to tune in for is six
        streams played for no one."""
        for path in self._radio or ():
            try:
                path.unlink(missing_ok=True)
            except OSError as refused:
                logger.warning("Could not take back the radio dealt in %s: %s", path, refused)
        self._radio = []

    # --- commands in --------------------------------------------------------

    def _drain_commands(self) -> None:
        """Take the queued verbs, keeping the case of what a verb carries.

        The Funestras fold the whole payload, which suits verbs that carry no
        argument; one here does — a spoken phrase, which is words rather than a
        keyword — so the keyword alone is folded (see :meth:`_apply`).
        """
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
        keyword = keyword.upper()  # what it carries keeps its case
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
        side = side_spoken_to(keyword, SIDES)
        if side is None:
            logger.warning("Unknown Fun Time verb dropped: %s", line)
            return
        action, argument = side_press(side, keyword.lower(), argument)
        if not marker and action in self._side_verbs:
            self._side_verbs[action](side)
            return
        if action in PANEL_PLACES:
            self._gallery.place_a_panel(side, action, argument)
            return
        if action == SAY and marker == ":":
            # The session owns the microphone for the whole room, so a spoken
            # command about one of these regions is heard THERE and sent here
            # as the words themselves — matched by this app's own vocabulary,
            # which is the only place that knows its collections and its parts.
            self._run_what_was_said(side, argument)
            return
        self._apply_side(side, action, argument, line)

    def _run_what_was_said(self, side: str, words: str) -> None:
        was_taking_a_request = self._gallery.taking_a_request()
        self._gallery.run_spoken_command(f"{side} {words}")
        taking_a_request = self._gallery.taking_a_request()
        if taking_a_request == was_taking_a_request:
            return
        self._request_side = side if taking_a_request else None
        self._tell_the_room(spelled_for(side, REQUEST_OPEN if taking_a_request
                                        else REQUEST_CLOSED))

    def _close_the_slideshow(self, side: str) -> None:
        self._drop_the_request_said_to(side)
        self._gallery.close_the_slideshow(side)

    def _close_the_slideshows(self) -> None:
        # Through the gallery, not slideshow by slideshow: it has to stop WANTING the
        # regions first, or each close it makes here is answered by the
        # base state opening again underneath it.
        self._drop_the_request_said_to(self._request_side)
        self._gallery.close_the_slideshows()

    def _drop_the_request_said_to(self, side: str | None) -> None:
        if side is None or side != self._request_side:
            return
        self._gallery.drop_the_request()
        self._request_side = None
        self._tell_the_room(spelled_for(side, REQUEST_CLOSED))

    def _tell_the_room(self, line: str) -> None:
        if self._session.dashboard_cmd_file is not None:
            append_command(self._session.dashboard_cmd_file, line)

    def _release(self) -> None:
        self._drop_the_request_said_to(self._request_side)
        self._released = True
        self._timer.stop()
        self.take_the_radio_back()
        self.released.emit()

    def _filter_enhanced(self) -> None:
        """The session's enhanced-only switch, pressed there and landing here.

        One switch in the session and two regions under it, so the press moves
        both and reads the pair to decide which way: anything narrowed widens,
        nothing narrowed narrows.  Flipped side by side they could disagree — a
        region whose set has nothing enhanced in it refuses the narrowing — and
        one lit switch cannot say that a room is half narrowed.
        """
        slideshows = [slideshow for slideshow in map(self._gallery.region_slideshow, SIDES)
                      if slideshow is not None]
        enhanced_only = not any(slideshow.hud_enhanced_mode for slideshow in slideshows)
        for slideshow in slideshows:
            slideshow.set_enhanced_mode(enhanced_only)

    def _apply_side(self, side: str, action: str, argument: str, line: str) -> None:
        """A press on *side*'s panel, onto whatever holds that side.

        The same answers a slideshow's own panel gets
        (:func:`~origenerator.slideshow_buttons.answer`): the session routes a
        Funestra's presses back here verbatim, and its own hotkeys spell the
        transport the same way, so one table says what every one of them means.
        """
        slideshow = self._gallery.region_slideshow(side)
        if slideshow is None:
            return  # an empty region has nothing to drive
        if not answer(slideshow, action, argument):
            logger.warning("Unanswered press for the %s slideshow dropped: %s", side, line)

    # --- the paused flag ----------------------------------------------------

    def _apply_paused(self) -> None:
        if self._session.paused_file is None:
            return
        paused = read_paused_state(self._session.paused_file, logger=logger)
        if paused == self._paused:
            return
        self._paused = paused
        # The gallery holds the flag and fans it out, so a slideshow opened between
        # this edge and the next one still opens frozen — the edge alone once
        # left a mid-pause slideshow playing.
        self._gallery.set_room_paused(paused)

    # --- status out ---------------------------------------------------------

    #: The whole of it: this app is up and answering.  It published six keys
    #: for years -- which side held a slideshow, what it was showing, whether it was
    #: locked -- and the session read none of them; it waits on this file
    #: appearing, and nothing else, to know the mode can be opened.  The owner
    #: settled that on 2026-09-05 (audit Q13): nothing was to be wired to read
    #: those six, so the channel goes and the signal stays.
    READY = "ready=1"

    def _publish_status(self) -> None:
        if self._session.status_file is None:
            return
        # Republished when it is not there as well as when it changes: the
        # session clears this file as it opens the mode, and a signal written
        # once would never come back for the session that cleared it.
        if self._published and self._session.status_file.exists():
            return
        self._published = publish_whole(self._session.status_file,
                                        self.READY + "\n")
