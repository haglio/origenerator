"""Fun Time's hands on a hosted Origenerator: the file channels, polled.

Fun Time drives its satellite players through a command file, a paused flag
and a status file (``player_core.file_channel`` / ``player_core.status``); a
hosted Origenerator answers the same idioms so the session reaches the region
shows the way it reaches the players:

* ``PORTRAIT_NEXT`` steps whatever holds the portrait region the way ``NEXT``
  steps the portrait player — same for ``PREV``/``TRASH``/``LOCK``/``RESET``
  and the landscape side.  ``OPEN_SHOWS`` fills both regions (the session
  switching INTO origenerator mode, which opens playing rather than empty) and
  ``CLOSE_SHOWS`` clears them again; ``FILTER_ENHANCED`` flips the show's
  enhanced-only switch, the one its own HUD carries and the session's console
  carries too; ``QUIT`` closes the app the way its own Ctrl+Alt+Q would.
* The paused flag freezes the shows the way it freezes the players, so
  OmniPause is one write here too — held by the gallery, not just edged onto
  the open shows, so a show opened mid-pause opens frozen.
* The status file says which regions are occupied (and by what) — a readout
  for the hosting session's diagnostics.
* A click on a show asks the room for OmniPause (:func:`ask_for_omnipause`) on
  the dashboard channel, where a player's click on its picture asks for it.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer

from origenerator.fun_time_mode import FunTimeSession
from origenerator.gui.show_buttons import answer
from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()
from player_core.file_channel import (
    append_command,
    consume_command_file,
    publish_whole,
    read_paused_state,
)

logger = logging.getLogger(__name__)

_POLL_MS = 150
_SIDES = ("portrait", "landscape")


def ask_for_omnipause(dashboard_cmd_file) -> None:
    append_command(dashboard_cmd_file, "omnipause_toggle")


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
    """Polls the session's channels and routes them onto the gallery's shows."""

    def __init__(self, session: FunTimeSession, gallery, parent=None):
        super().__init__(parent)
        self._session = session
        self._gallery = gallery
        self._paused = False
        self._last_status: str | None = None
        # The verbs about the session's shows as a whole, rather than one side's.
        self._session_verbs = {
            "OPEN_SHOWS": lambda: self._gallery.fill_the_regions(),
            # Through the gallery, not show by show: it has to stop WANTING the
            # regions first, or each close it makes here is answered by the
            # base state opening again underneath it.
            "CLOSE_SHOWS": lambda: self._gallery.close_the_shows(),
            "FILTER_ENHANCED": self._filter_enhanced,
            "QUIT": lambda: self._gallery.window().close(),
        }
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._drain_commands()
        self._apply_paused()
        self._publish_status()

    # --- commands in --------------------------------------------------------

    def _drain_commands(self) -> None:
        """Take the queued verbs, keeping the case of what a verb carries.

        The players fold the whole payload, which suits verbs that carry no
        argument; one here does — a spoken phrase, which is words rather than a
        keyword — so the keyword alone is folded (see :meth:`_apply`).
        """
        if self._session.command_file is None:
            return
        for verb in consume_command_file(self._session.command_file, logger=logger,
                                         uppercase=False):
            self._apply(verb.strip())

    def _apply(self, line: str) -> None:
        if not line:
            return
        keyword, marker, argument = _split_argument(line)
        keyword = keyword.upper()  # what it carries keeps its case
        if not marker and keyword in self._session_verbs:
            self._session_verbs[keyword]()
            return
        side, _, action = keyword.partition("_")
        side = side.lower()
        if side not in _SIDES:
            logger.warning("Unknown Fun Time verb dropped: %s", line)
            return
        if action == "SAY" and marker == ":":
            # The session owns the microphone for the whole room, so a spoken
            # command about one of these regions is heard THERE and sent here
            # as the words themselves — matched by this app's own vocabulary,
            # which is the only place that knows its shelves and its parts.
            self._gallery.run_spoken_command(f"{side} {argument}")
            return
        self._apply_side(side, action.lower(), argument, line)

    def _filter_enhanced(self) -> None:
        """The session's enhanced-only switch, pressed there and landing here.

        One switch in the session and two regions under it, so the press moves
        both and reads the pair to decide which way: anything narrowed widens,
        nothing narrowed narrows.  Flipped side by side they could disagree — a
        region whose set has nothing enhanced in it refuses the narrowing — and
        one lit switch cannot say that a room is half narrowed.
        """
        shows = [show for show in map(self._gallery.region_show, _SIDES)
                 if show is not None]
        enhanced_only = not any(show.hud_enhanced_mode for show in shows)
        for show in shows:
            show.set_enhanced_mode(enhanced_only)

    def _apply_side(self, side: str, action: str, argument: str, line: str) -> None:
        """A press on *side*'s panel, onto whatever holds that side.

        The same answers a show's own panel gets
        (:func:`~origenerator.gui.show_buttons.answer`): the session routes a
        player's presses back here verbatim, and its own hotkeys spell the
        transport the same way, so one table says what every one of them means.
        """
        show = self._gallery.region_show(side)
        if show is None:
            return  # an empty region has nothing to drive
        if not answer(show, action, argument):
            logger.warning("Unanswered press for the %s show dropped: %s", side, line)

    # --- the paused flag ----------------------------------------------------

    def _apply_paused(self) -> None:
        if self._session.paused_file is None:
            return
        paused = read_paused_state(self._session.paused_file, logger=logger)
        if paused == self._paused:
            return
        self._paused = paused
        # The gallery holds the flag and fans it out, so a show opened between
        # this edge and the next one still opens frozen — the edge alone once
        # left a mid-pause show playing.
        self._gallery.set_session_paused(paused)

    # --- status out ---------------------------------------------------------

    def _publish_status(self) -> None:
        if self._session.status_file is None:
            return
        lines = []
        for side in _SIDES:
            show = self._gallery.region_show(side)
            lines.append(f"{side}_active={'1' if show is not None else '0'}")
            path = show.current_media_path() if show is not None else ""
            lines.append(f"{side}_video={path}")
            locked = show is not None and bool(show.locked)
            lines.append(f"{side}_locked={'1' if locked else '0'}")
        text = "".join(f"{line}\n" for line in lines)
        if text == self._last_status:
            return
        # Written whole, and remembered only once it lands — a failed write
        # must retry next tick, not be treated as published.
        if publish_whole(self._session.status_file, text):
            self._last_status = text
