"""The standalone window's link to a Fun Time session, on one poll.

Three things ride that tick: the offer a session takes this window over
through, standing for as long as the window does; the takeover itself; and the
session's standing claim on the OSR2.  The claim is read whether or not the
takeover ever arrives, because it is the one device and a session that never
reached this window is driving it anyway.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer

from origenerator.fun_time_mode import (
    OFFER_NAME,
    FunTimeSession,
    a_session_holds_the_device,
    offer_of_this_process,
    take_the_takeover,
)

logger = logging.getLogger(__name__)

_POLL_MS = 250


class FunTimeWatch(QObject):
    def __init__(self, state_dir: Path, *, take_over: Callable[[FunTimeSession], None],
                 device_claimed: Callable[[bool], None] | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._state_dir = state_dir
        self._take_over = take_over
        self._device_claimed = device_claimed or (lambda held: None)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._answer_the_session)
        self.renew()

    def renew(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._timer.start()
        self._answer_the_session()

    def stands_its_offer(self) -> bool:
        return self._timer.isActive()

    def _stand_the_offer(self) -> None:
        """Put the offer back whenever it stops naming this window.

        Written once, it is one deletion away from a window no session can find
        -- and a session that cannot find it launches a second copy beside it
        and leaves this one on the device.  A second instance of this app
        overwrites it in the ordinary course of things.
        """
        offer = self._state_dir / OFFER_NAME
        mine = offer_of_this_process()
        try:
            standing = offer.read_text(encoding="utf-8")
            if standing == mine:
                return
            if standing != offer_of_this_process(starting=True):
                logger.info("The offer to Fun Time named someone else; standing ours again")
        except FileNotFoundError:
            pass
        except OSError:
            logger.info("The offer to Fun Time could not be read; standing ours again")
        offer.write_text(mine, encoding="utf-8")

    def _answer_the_session(self) -> None:
        self._stand_the_offer()
        self._device_claimed(a_session_holds_the_device(self._state_dir))
        session = take_the_takeover(self._state_dir, pid=os.getpid())
        if session is None:
            return
        logger.info("A Fun Time session asked for this window")
        self.withdraw()
        self._take_over(session)

    def withdraw(self) -> None:
        self._timer.stop()
        (self._state_dir / OFFER_NAME).unlink(missing_ok=True)
