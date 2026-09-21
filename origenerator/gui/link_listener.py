"""Where a click on one of this app's notifications reaches the running app.

Windows answers a click by running this checkout's handler
(:mod:`origenerator.app_link`), which hands the generation over here or starts
the app carrying it; both arrive at :meth:`LinkListener.answer_with`. Standing
from the moment there is an event loop rather than from the moment there is a
window, because a launch here is slow and a click during one would otherwise
find nobody listening and start a second copy.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer

from origenerator import app_link

logger = logging.getLogger(__name__)


class LinkListener(QObject):
    """The channel this checkout's clicks arrive on, and what is waiting on it."""

    def __init__(self, *, checkout: Path = app_link.CHECKOUT, environ=None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._answer: Callable[[str], None] | None = None
        self._waiting: list[str] = []
        # Taken out of the environment, not merely read: every child this app
        # starts would otherwise inherit an instruction meant for this launch.
        self._asked_for(
            (os.environ if environ is None else environ).pop(app_link.CARRIED_IN, ""))
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._take_a_click)
        if not self._server.listen(app_link.channel_for(checkout)):
            logger.warning("Clicks on this app's notices cannot be answered here: %s",
                           self._server.errorString())

    def answer_with(self, go_to: Callable[[str], None]) -> None:
        """Take every click to *go_to*, starting with any that arrived already."""
        self._answer = go_to
        waiting, self._waiting = self._waiting, []
        for generation in waiting:
            go_to(generation)

    def _take_a_click(self) -> None:
        socket = self._server.nextPendingConnection()
        said = bytearray(bytes(socket.readAll()))
        socket.readyRead.connect(lambda: said.extend(bytes(socket.readAll())))
        socket.disconnected.connect(lambda: self._heard(bytes(said), socket))

    def _heard(self, said: bytes, socket) -> None:
        socket.deleteLater()
        self._asked_for(said.decode("ascii", "replace").strip())

    def _asked_for(self, generation: str) -> None:
        """Answer a click, or hold it until there is a window to answer it in.

        Whatever arrives is read as strictly as the link it came from
        (:func:`origenerator.app_link.a_generation`): a link is open to anything
        that can reach a shell.
        """
        wanted = app_link.a_generation(generation)
        if wanted is None:
            if generation:
                logger.warning("A click asked for something that is not a generation")
            return
        logger.info("A click on a notice asked for %s", wanted)
        if self._answer is None:
            self._waiting.append(wanted)
        else:
            self._answer(wanted)
