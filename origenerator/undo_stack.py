"""One undo stack and the redo stack behind it. Knows nothing of what it undoes.

Session-scoped, bounded, and generic: a step is a label, a way to reverse it,
and optionally a way to run it again. What it reverses — a delete, a rename, a
folder gathered by hand — is entirely the caller's business (see
:mod:`origenerator.gallery_actions`, which holds one).

Two things about it are unusual and deliberate. **A redo re-runs the original
mutation** rather than inverting the undo: the same call with the same
arguments, so it files fresh trash batches and a fresh undo entry rather than
trying to re-drive the ones the undo already spent. That is what lets a step be
undone and redone any number of times. And because a re-run pushes an entry of
its own, ``_redoing`` is what stops that entry from clearing the redo stack it
just came off — the older redos behind it are still good.

Any *new* step does clear it, as everywhere else: once history has forked, the
branch you left is gone.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class UndoEntry:
    """One reversible step."""

    # ``undo`` returns something for the caller to navigate back to (a restored
    # generation's prompt id), or ``None`` when there's nowhere in particular to
    # go (e.g. a rename).
    label: str
    undo: Callable[[], str | None]
    commit: Callable[[], None] | None = None  # run when dropped without undoing
    # Re-applies the mutation, pushing its own fresh undo entry as it goes. An
    # entry without one can be undone but not redone, and simply doesn't reach
    # the redo stack.
    redo: Callable[[], None] | None = None


class UndoStack:
    """The steps taken, the steps taken back, and the limit on the first."""

    def __init__(self, limit: int = 50):
        self._limit = limit
        self._entries: list[UndoEntry] = []
        self._redoable: list[UndoEntry] = []
        self._redoing = False

    def push(self, entry: UndoEntry) -> None:
        if not self._redoing:
            self._redoable.clear()  # a new step forks history; the branch is gone
        self._entries.append(entry)
        while len(self._entries) > self._limit:
            evicted = self._entries.pop(0)
            if evicted.commit is not None:
                evicted.commit()

    def entries(self) -> tuple[UndoEntry, ...]:
        """What can still be undone, oldest first."""
        return tuple(self._entries)

    def can_undo(self) -> bool:
        return bool(self._entries)

    def undo_label(self) -> str | None:
        return self._entries[-1].label if self._entries else None

    def undo(self) -> str | None:
        """Reverse the most recent step, returning whatever it says to navigate
        back to."""
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
        """Re-apply the most recently undone step, by running it again.

        The re-run files its own undo entry, so the step lands back on the undo
        stack able to be undone (and redone) as many times as the user likes.
        """
        if not self._redoable:
            return
        entry = self._redoable.pop()
        self._redoing = True
        try:
            entry.redo()
        finally:
            self._redoing = False
        return
