from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class UndoEntry:
    label: str
    undo: Callable[[], str | None]
    commit: Callable[[], None] | None = None
    redo: Callable[[], None] | None = None


class UndoStack:
    def __init__(self, limit: int = 50):
        self._limit = limit
        self._entries: list[UndoEntry] = []
        self._redoable: list[UndoEntry] = []
        self._redoing = False

    def push(self, entry: UndoEntry) -> None:
        if not self._redoing:
            self._redoable.clear()
        self._entries.append(entry)
        while len(self._entries) > self._limit:
            evicted = self._entries.pop(0)
            if evicted.commit is not None:
                evicted.commit()

    def entries(self) -> tuple[UndoEntry, ...]:
        return tuple(self._entries)

    def can_undo(self) -> bool:
        return bool(self._entries)

    def undo_label(self) -> str | None:
        return self._entries[-1].label if self._entries else None

    def undo(self) -> str | None:
        if not self._entries:
            return None
        entry = self._entries.pop()
        focus = entry.undo()
        if entry.redo is not None:
            self._redoable.append(entry)
        return focus

    def can_redo(self) -> bool:
        return bool(self._redoable)

    def redo_label(self) -> str | None:
        return self._redoable[-1].label if self._redoable else None

    def redo(self) -> None:
        if not self._redoable:
            return
        entry = self._redoable.pop()
        self._redoing = True
        try:
            entry.redo()
        finally:
            self._redoing = False
        return
