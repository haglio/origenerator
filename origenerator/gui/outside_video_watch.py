from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer

from origenerator import outside_videos
from origenerator.gui.off_thread import run_off_thread
from origenerator.outside_videos import Places

logger = logging.getLogger(__name__)

LOOK_EVERY_MS = 10 * 60 * 1000


class OutsideVideoWatch(QObject):
    def __init__(self, db, places: Callable[[], Places | None], *, parent: QObject | None = None,
                 run=run_off_thread, scan=outside_videos.scan, every_ms: int = LOOK_EVERY_MS):
        super().__init__(parent)
        self._db, self._places, self._run, self._scan = db, places, run, scan
        self._looking = False
        self._closing = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(every_ms)
        self._timer.timeout.connect(self.look)

    def start(self) -> None:
        self._timer.start()
        self.look()

    def stop(self) -> None:
        self._closing.set()
        self._timer.stop()

    def look(self) -> None:
        places = self._places()
        if places is None or self._looking or self._closing.is_set():
            return
        self._looking = True
        closing, db, scan = self._closing, self._db, self._scan
        self._run(lambda: scan(db, places, keep_going=lambda: not closing.is_set()),
                  self._looked, owner=self)

    def _looked(self, brought_in) -> None:
        self._looking = False
        if brought_in:
            logger.info("Brought in %d video(s) other sources made", brought_in)

