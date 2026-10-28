"""The standalone window's link to a Fun Time session, on one poll.

Three things ride that tick: the offer a session takes this window over
through, standing for as long as the window does; the takeover itself; and the
session's standing claim on the OSR2.  The claim is read whether or not the
takeover ever arrives, because it is the one device and a session that never
reached this window is driving it anyway.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app_support import origenerator_handoff as handoff
from PyQt6.QtCore import QObject, QTimer

from origenerator.fun_time_mode import FunTimeSession, take_the_takeover

logger = logging.getLogger(__name__)

_POLL_MS = 250


class FunTimeWatch(QObject):
    def __init__(self, state_dir: Path, *, take_over: Callable[[FunTimeSession], None],
                 device_claimed: Callable[[bool], None] | None = None,
                 showing_on: Callable[[], str | None] | None = None,
                 library_state_dir: Path | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._me = handoff.this_process()
        self._state_dirs = tuple(dict.fromkeys((state_dir, library_state_dir or state_dir)))
        self._take_over = take_over
        self._device_claimed = device_claimed or (lambda held: None)
        self._showing_on = showing_on or (lambda: None)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._answer_the_session)
        self.renew()

    def renew(self) -> None:
        for state_dir in self._state_dirs:
            state_dir.mkdir(parents=True, exist_ok=True)
        self._timer.start()
        self._answer_the_session()

    def stands_its_offer(self) -> bool:
        return self._timer.isActive()

    def _stand_the_offer(self) -> None:
        for state_dir in self._state_dirs:
            self._stand_the_offer_in(state_dir / handoff.OFFER)

    def _stand_the_offer_in(self, offer: Path) -> None:
        mine = handoff.offer_of(self._me)
        try:
            standing = offer.read_text(encoding="utf-8")
            if standing == mine:
                return
            if standing != handoff.offer_of(self._me, starting=True):
                logger.info("The offer to Fun Time named someone else; standing ours again")
        except FileNotFoundError:
            pass
        except OSError:
            logger.info("The offer to Fun Time could not be read; standing ours again")
        offer.write_text(mine, encoding="utf-8")

    def _mark_the_slideshow(self) -> None:
        shape = self._showing_on()
        mark = None if shape is None else handoff.slideshow_mark_of(self._me, shape)
        for state_dir in self._state_dirs:
            _stand(state_dir / handoff.SHOWING, mark)

    def _answer_the_session(self) -> None:
        self._stand_the_offer()
        self._mark_the_slideshow()
        self._device_claimed(any(map(handoff.a_session_claims_the_osr2, self._state_dirs)))
        session = next(filter(None, (take_the_takeover(state_dir, pid=self._me.pid)
                                     for state_dir in self._state_dirs)), None)
        if session is None:
            return
        logger.info("A Fun Time session asked for this window")
        self.withdraw()
        self._take_over(session)

    def withdraw(self) -> None:
        self._timer.stop()
        handoff.withdraw_the_offer(*self._state_dirs)


def _stand(path: Path, mark: str | None) -> None:
    if mark is None:
        path.unlink(missing_ok=True)
        return
    try:
        if path.read_text(encoding="utf-8") == mark:
            return
    except OSError:
        pass
    path.write_text(mark, encoding="utf-8")
