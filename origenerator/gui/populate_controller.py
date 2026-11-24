from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class PopulateController(QObject):
    stopped = Signal(str)

    def __init__(self, launch, parent=None):
        super().__init__(parent)
        self._launch = launch
        self._active: dict[str, None] = {}
        self._runs: dict[str, str] = {}
        self._made: dict[str, set[str]] = {}

    def is_active(self, key: str) -> bool:
        return key in self._active

    def active_keys(self) -> tuple[str, ...]:
        return tuple(self._active)

    def start(self, key: str) -> None:
        if key in self._active:
            return
        self._active[key] = None
        if not self._launch(key):
            self._forget(key)

    def note_launch(self, key: str, *, origin: str) -> None:
        if key in self._active:
            self._runs[origin] = key

    def note_landed(self, *, origin: str, prompt_id: str) -> bool:
        key = self._runs.pop(origin, None)
        if key is None:
            return False
        self._made.setdefault(key, set()).update((origin, prompt_id))
        return True

    def owns(self, origin: str) -> bool:
        return origin in self._runs

    def made_ids(self) -> frozenset[str]:
        return frozenset().union(*self._made.values())

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
            self._forget(key)
            self.stopped.emit(key)

    def _forget(self, key: str) -> None:
        self._active.pop(key, None)
        self._made.pop(key, None)
        self._runs = {origin: of for origin, of in self._runs.items() if of != key}
