"""Drive the OSR2 from a playing video's funscript, one device at a time.

The app owns a single :class:`Osr2Driver`. When a tab enables "Drive OSR2" for a
scripted video, the view points the driver at that preview's media player and the
video's actions; the driver then streams T-code toward the next action on a timer,
following the player's position (wrapping onto the script as the preview loops). It
pauses genau while it drives and parks the device + restores genau when it stops.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer

from origenerator.config import (
    OSR2_BROKER_HOST, OSR2_GENAU_ENABLED_FILE, OSR2_TCODE_UDP_PORT,
)
from origenerator.funscript import funscript_path_for, read_actions
from origenerator.osr2 import Osr2Broker

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 50


def drive_target_for(video_path, player):
    """Bundle a video with the player showing it into the driver's input —
    ``(video_path, player, actions)`` — or ``None`` when there's nothing to drive:
    no video, or a video with no funscript beside it.

    The one driver can follow either of two foreground surfaces — the front config
    tab's preview or an open fullscreen view — so both describe their target through
    this, keeping the ``(path, player, actions)`` contract in a single place.
    """
    if video_path is None:
        return None
    actions = read_actions(funscript_path_for(video_path))
    if not actions:
        return None
    return video_path, player, actions


class Osr2Driver(QObject):
    def __init__(self, broker=None, *, interval_ms: int = _POLL_INTERVAL_MS, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker(
            OSR2_BROKER_HOST, OSR2_TCODE_UDP_PORT,
            genau_enabled_file=OSR2_GENAU_ENABLED_FILE,
        )
        self._player = None
        self._actions: list[tuple[int, int]] = []  # (at_ms, pos), sorted by time
        self._duration_ms = 0
        self._streaming = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)

    def start(self, player, actions: list[dict]) -> None:
        """Take over the device for ``player``'s video, streaming ``actions``.

        Releases any video already driving first, so only one ever owns the device.
        A video with no actions is a no-op (genau is left alone).
        """
        self.stop()
        if not actions:
            return
        self._player = player
        self._actions = sorted((int(a["at"]), int(a["pos"])) for a in actions)
        self._duration_ms = self._actions[-1][0]
        self._streaming = False  # for a one-shot "first T-code sent" log line
        self._broker.pause_genau()
        self._timer.start()
        logger.info("OSR2 drive engaged: %d actions, %d ms; genau paused",
                    len(self._actions), self._duration_ms)

    def stop(self) -> None:
        """Release the device: stop streaming, park it, and restore genau."""
        if self._player is None:
            return
        self._timer.stop()
        self._player = None
        self._actions = []
        self._duration_ms = 0
        self._broker.park()
        self._broker.restore_genau()
        logger.info("OSR2 drive released: parked, genau restored")

    def poll(self) -> None:
        """Advance the device toward the action following the current playhead.

        Driven purely by ``position()`` — the driver doesn't gate on the player's
        playback state (the info-pane preview auto-plays with no pause control; the
        Drive OSR2 button is the on/off). A stalled playhead simply holds the device
        at the current target.
        """
        player = self._player
        if player is None:
            return
        now_ms = player.position()
        if self._duration_ms > 0:
            now_ms %= self._duration_ms  # the preview loops; fold onto the script
        pos, interval = self._next_target(now_ms)
        if pos is not None:
            self._broker.send_position(pos, interval)
            if not self._streaming:
                self._streaming = True
                logger.info("OSR2 drive streaming: first T-code pos=%d interval=%d "
                            "(playhead %d ms)", pos, interval, now_ms)

    def _next_target(self, now_ms: int):
        """The next action strictly after ``now_ms`` and the time until it — or, past
        the last action, the first action of the next loop."""
        for at, pos in self._actions:
            if at > now_ms:
                return pos, max(1, at - now_ms)
        if self._actions:
            at, pos = self._actions[0]
            return pos, max(1, self._duration_ms - now_ms + at)
        return None, 0
