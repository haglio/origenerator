"""Fun Time's hands on a hosted Origenerator: the file channels, polled.

Fun Time drives its satellite players through a command file, a paused flag
and a status file (``player_core.file_channel`` / ``player_core.status``); a
hosted Origenerator answers the same idioms so the session reaches the region
shows the way it reaches the players:

* ``PORTRAIT_NEXT`` steps whatever holds the portrait region the way ``NEXT``
  steps the portrait player — same for ``PREV``/``TRASH``/``LOCK``/``RESET``
  and the landscape side.  ``OPEN_SHOWS`` fills both regions (the session
  switching INTO origenerator mode, which opens playing rather than empty) and
  ``CLOSE_SHOWS`` clears them again; ``QUIT`` closes the app the way its own
  Ctrl+Alt+Q would.
* The paused flag freezes the shows the way it freezes the players, so
  OmniPause is one write here too — held by the gallery, not just edged onto
  the open shows, so a show opened mid-pause opens frozen.
* The status file says which regions are occupied (and by what) — a readout
  for the hosting session's diagnostics.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer

from origenerator.fun_time_mode import FunTimeSession
from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()
from player_core.file_channel import consume_command_file, publish_whole, read_paused_state

logger = logging.getLogger(__name__)

_POLL_MS = 150
_SIDES = ("portrait", "landscape")


class FunTimeBridge(QObject):
    """Polls the session's channels and routes them onto the gallery's shows."""

    def __init__(self, session: FunTimeSession, gallery, parent=None):
        super().__init__(parent)
        self._session = session
        self._gallery = gallery
        self._paused = False
        self._last_status: str | None = None
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

    def _apply(self, verb: str) -> None:
        if not verb:
            return
        keyword, marker, argument = verb.partition(":")
        verb = keyword.upper() + marker + argument  # the words keep their case
        if verb == "OPEN_SHOWS":
            self._gallery.fill_the_regions()
            return
        if verb == "CLOSE_SHOWS":
            # Through the gallery, not show by show: it has to stop WANTING the
            # regions first, or each close it makes here is answered by the
            # base state opening again underneath it.
            self._gallery.close_the_regions()
            return
        if verb == "QUIT":
            self._gallery.window().close()
            return
        side, _, action = verb.partition("_")
        side = side.lower()
        if side not in _SIDES:
            logger.warning("Unknown Fun Time verb dropped: %s", verb)
            return
        spoken, marker, phrase = action.partition(":")
        if spoken == "SAY":
            # The session owns the microphone for the whole room, so a spoken
            # command about one of these regions is heard THERE and sent here
            # as the words themselves — matched by this app's own vocabulary,
            # which is the only place that knows its shelves and its parts.
            self._gallery.run_spoken_command(f"{side} {phrase}")
            return
        if marker:
            logger.warning("Unknown Fun Time verb dropped: %s", verb)
            return
        self._apply_side(side, action)

    def _apply_side(self, side: str, action: str) -> None:
        """One transport verb onto whatever holds *side*.

        Whatever holds it answers :class:`~origenerator.gui.show_host.ShowHost`,
        so the verb is handed straight over; an unknown verb is what falls
        through, not an unanswered one.
        """
        show = self._gallery.region_show(side)
        if show is None:
            return  # an empty region has nothing to drive
        if action == "NEXT":
            show.stroke_step(1)
        elif action == "PREV":
            show.stroke_step(-1)
        elif action == "TRASH":
            show.stroke_cull()
        elif action == "LOCK":
            show.stroke_toggle_hold()
        elif action == "RESET":
            show.stroke_reset()

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
