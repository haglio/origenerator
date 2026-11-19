from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import consume_command_file
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

_LOOK_EVERY_S = 0.01


class AsksFromTheFunestra(QObject):
    asked = Signal(str, float)

    def __init__(self, asks_file: Path, *, clock: Callable[[], float] = time.monotonic,
                 parent=None) -> None:
        super().__init__(parent)
        self._asks_file = Path(asks_file)
        self._clock = clock
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None

    def read_now(self) -> None:
        at = self._clock()
        for line in consume_command_file(self._asks_file, uppercase=False):
            self.asked.emit(line, at)

    def start(self) -> None:
        if self._reader is not None:
            return
        self._reader = threading.Thread(target=self._read_until_stopped,
                                        name="funestra-asks", daemon=True)
        self._reader.start()

    def _read_until_stopped(self) -> None:
        while not self._stop.wait(_LOOK_EVERY_S):
            try:
                self.read_now()
            except Exception:
                logger.exception("Reading what a Funestra asked failed")

    def stop(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join()
            self._reader = None
