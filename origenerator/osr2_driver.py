"""Drive the OSR2 from a playing video's funscript, one device at a time.

The app owns a single :class:`Osr2Driver`. When a tab enables "Drive OSR2" for a
scripted video, the view points the driver at that preview's media player and the
video's actions; the driver then streams T-code toward the next action on a timer,
following the player's position (wrapping onto the script as the preview loops). It
pauses genau while it drives and parks the device + restores genau when it stops.
"""

from __future__ import annotations

import logging

from app_support.funscript import read_actions
from player_core.funscript import Funscript
from PyQt6.QtCore import QObject, QTimer

from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.funscript import funscript_of
from origenerator.osr2 import Osr2Broker

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 50


def drive_target_for(video_path, player):
    """Bundle a video with the player showing it into the driver's input —
    ``(video_path, player, actions)`` — or ``None`` when there's nothing to drive:
    no video, or a video with no funscript to its name.

    The one driver can follow either of two foreground surfaces — the front config
    tab's preview or an open fullscreen show — so both describe their target through
    this, keeping the ``(path, player, actions)`` contract in a single place.
    """
    if video_path is None:
        return None
    actions = read_actions(funscript_of(video_path, output_dir=COMFYUI_OUTPUT_DIR))
    if not actions:
        return None
    return video_path, player, actions


class Osr2Driver(QObject):
    def __init__(self, broker=None, *, interval_ms: int = _POLL_INTERVAL_MS, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker()
        self._player = None
        self._actions: list[tuple[int, int]] = []  # (at_ms, pos), sorted by time
        # The same actions as the family's own model, for the line the console
        # draws: where the script has the device at any moment.
        self._script: Funscript | None = None
        self._duration_ms = 0
        self._streaming = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)

    def start(self, player, actions: list[dict]) -> None:
        """Take over the device for ``player``'s video, streaming ``actions``.

        Releases any video already driving first, so only one ever owns the device.
        A video with no actions is a no-op.
        """
        self.stop()
        if not actions:
            return
        self._player = player
        self._actions = sorted((int(a["at"]), int(a["pos"])) for a in actions)
        self._script = Funscript(self._actions)
        self._duration_ms = self._actions[-1][0]
        self._streaming = False  # for a one-shot "first T-code sent" log line
        self._timer.start()
        logger.info("OSR2 drive engaged: %d actions, %d ms",
                    len(self._actions), self._duration_ms)

    def stop(self) -> None:
        """Release the device: stop streaming and park it."""
        if self._player is None:
            return
        self._timer.stop()
        self._player = None
        self._actions = []
        self._script = None
        self._duration_ms = 0
        self._broker.park()
        logger.info("OSR2 drive released: parked")

    @property
    def active(self) -> bool:
        """Whether this is the thing sending to the device right now."""
        return self._player is not None

    def trace(self, count: int, seconds: float) -> tuple[float, ...]:
        """The script's line from the playhead forward, as *count* heights 0-1
        spanning *seconds* -- the motion the device is about to be asked for,
        which is what the console draws in the Robot Hand's place while a
        funscript has the device.

        Folded onto the script the same way the stream is (the preview loops),
        so the picture and the wire read the same script at the same moment.
        """
        if self._script is None or self._player is None or count <= 0:
            return ()
        now = int(self._player.position())
        step = seconds * 1000 / max(1, count - 1)
        return tuple(self._script.position_at(self._folded(now + round(i * step))) / 100
                     for i in range(count))

    def _folded(self, at_ms: int) -> int:
        """*at_ms* wrapped onto the script, as the stream wraps the playhead."""
        return at_ms % self._duration_ms if self._duration_ms > 0 else at_ms

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
        now_ms = self._folded(int(player.position()))  # the preview loops
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
