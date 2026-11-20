from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app_support import origenerator_handoff as handoff
from app_support.written_file import ReadWhenChanged, WrittenFile
from PySide6.QtCore import QObject, QTimer

from origenerator.fun_time_mode import FunTimeSession, take_the_takeover

logger = logging.getLogger(__name__)

_POLL_MS = 250


class FunTimeWatch(QObject):
    def __init__(self, state_dir: Path, *, take_over: Callable[[FunTimeSession], None],
                 device_claimed: Callable[[bool], None] | None = None,
                 showing_on: Callable[[], str | None] | None = None,
                 library_state_dir: Path | None = None):
        super().__init__()
        self._me = handoff.this_process()
        self._state_dirs = tuple(dict.fromkeys((state_dir, library_state_dir or state_dir)))
        self._take_over = take_over
        self._device_claimed = device_claimed or (lambda held: None)
        self._showing_on = showing_on or (lambda: None)
        self._offers = tuple(_Stood(state_dir / handoff.OFFER) for state_dir in self._state_dirs)
        self._marks = tuple(_Stood(state_dir / handoff.SHOWING) for state_dir in self._state_dirs)
        self._claims = tuple(ReadWhenChanged(state_dir / handoff.SESSION, handoff.the_osr2_claim_in)
                             for state_dir in self._state_dirs)
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
        for offer in self._offers:
            self._stand_the_offer_in(offer)

    def _stand_the_offer_in(self, offer: _Stood) -> None:
        mine = handoff.offer_of(self._me)
        if offer.as_left(mine):
            return
        try:
            standing = offer.path.read_text(encoding="utf-8")
            if standing == mine:
                offer.found(mine)
                return
            if standing != handoff.offer_of(self._me, starting=True):
                logger.info("The offer to Fun Time named someone else; standing ours again")
        except FileNotFoundError:
            pass
        except OSError:
            logger.info("The offer to Fun Time could not be read; standing ours again")
        offer.write(mine)

    def _mark_the_slideshow(self) -> None:
        shape = self._showing_on()
        mark = None if shape is None else handoff.slideshow_mark_of(self._me, shape)
        for stood in self._marks:
            _stand(stood, mark)

    def _a_session_claims_the_osr2(self) -> bool:
        return any(claim is not None and claim.is_running()
                   for claim in (claimed.latest() for claimed in self._claims))

    def _answer_the_session(self) -> None:
        self._stand_the_offer()
        self._mark_the_slideshow()
        self._device_claimed(self._a_session_claims_the_osr2())
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


_NOTHING_SEEN_YET = object()


class _Stood:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._written = WrittenFile(path)
        self._left = _NOTHING_SEEN_YET

    def as_left(self, wanted: str | None) -> bool:
        if wanted is None and self._left is None:
            return True
        written_since = self._written.may_have_been_written()
        return wanted == self._left and not written_since

    def found(self, holding: str | None) -> None:
        self._written.was_read()
        self._left = holding

    def write(self, text: str) -> None:
        self._left = _NOTHING_SEEN_YET
        self.path.write_text(text, encoding="utf-8")


def _stand(stood: _Stood, mark: str | None) -> None:
    if stood.as_left(mark):
        return
    if mark is None:
        stood.path.unlink(missing_ok=True)
        stood.found(None)
        return
    try:
        if stood.path.read_text(encoding="utf-8") == mark:
            stood.found(mark)
            return
    except OSError:
        pass
    stood.write(mark)
