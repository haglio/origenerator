from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class AutoGenerateController(QObject):
    stopped = pyqtSignal(str)

    def __init__(self, launch, parent=None):
        super().__init__(parent)
        self._launch = launch
        self._active: set[str] = set()

    def is_active(self, key: str) -> bool:
        return key in self._active

    def active_key(self) -> str | None:
        return next(iter(self._active), None)

    def start(self, key: str) -> None:
        if key in self._active:
            return
        if not self._launch(key):
            return
        for other in list(self._active):
            self._end(other)
        self._active.add(key)

    def stop(self, key: str) -> None:
        self._end(key)

    def note_finished(self, key: str) -> None:
        self._advance(key)

    def note_canceled(self, key: str) -> None:
        self._advance(key)

    def note_failed(self, key: str) -> None:
        self._end(key)

    def stop_all(self) -> None:
        for key in list(self._active):
            self._end(key)

    def _advance(self, key: str) -> None:
        if key in self._active and not self._launch(key):
            self._end(key)

    def _end(self, key: str) -> None:
        if key in self._active:
            self._active.discard(key)
            self.stopped.emit(key)
