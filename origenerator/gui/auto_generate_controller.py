"""Keeps re-launching a settings folder's re-roll until the user stops it.

"Repeatedly generate in a folder" is the gallery re-roll on a loop: each time a
folder's fresh variation finishes, launch another, until the user toggles it off
or one fails. This owns none of the generation machinery — it drives the existing
re-roll through an injected ``launch(key)`` and is told of each outcome via
:meth:`note_finished`/:meth:`note_canceled`/:meth:`note_failed`, so it stays free
of the view and the job internals and unit-tests without them.

Stopping is the user's word alone — :meth:`stop` (the Auto toggle) and
:meth:`stop_all` (Esc). Cancelling the variation being made is not that word: it
throws away *this seed*, which is what a loop of random seeds is for, so the loop
takes it as its cue to try another at once.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class AutoGenerateController(QObject):
    stopped = pyqtSignal(str)  # (folder key) a folder's loop ended (stop or failure)

    def __init__(self, launch, parent=None):
        super().__init__(parent)
        self._launch = launch
        self._active: set[str] = set()

    def is_active(self, key: str) -> bool:
        return key in self._active

    def start(self, key: str) -> None:
        if key in self._active:
            return  # already looping this folder
        if self._launch(key):
            self._active.add(key)

    def stop(self, key: str) -> None:
        """Stop a folder's loop — the in-flight variation still lands, but no more
        are launched after it."""
        self._end(key)

    def note_finished(self, key: str) -> None:
        """A folder's re-roll finished — launch the next if still looping, ending
        the loop if that next one can't start."""
        self._advance(key)

    def note_canceled(self, key: str) -> None:
        """A folder's re-roll was cancelled — try another seed straight away.

        Cancel means "not this one", not "stop": a loop of random seeds is exactly
        the place to throw one away, and having to re-arm Auto after every discard
        made the button fight the user. Only :meth:`stop`/:meth:`stop_all` — the
        toggle and Esc — end a loop.
        """
        self._advance(key)

    def note_failed(self, key: str) -> None:
        """A folder's re-roll failed — end the loop rather than spin on a broken
        workflow."""
        self._end(key)

    def any_active(self) -> bool:
        return bool(self._active)

    def stop_all(self) -> None:
        """End every running loop at once (e.g. the user pressed Esc)."""
        for key in list(self._active):
            self._end(key)

    def rekey(self, old_key: str, new_key: str) -> None:
        """Move a running loop to a new folder key — its prompt was voice-edited to
        settings that belong in a different folder, so the loop follows it there."""
        if old_key in self._active:
            self._active.discard(old_key)
            self._active.add(new_key)

    def _advance(self, key: str) -> None:
        """One variation ended without the user stopping the loop: launch the next
        if still looping, ending the loop only if that next one can't start — a
        loop with nothing running and nothing launchable is a dead one."""
        if key in self._active and not self._launch(key):
            self._end(key)

    def _end(self, key: str) -> None:
        if key in self._active:
            self._active.discard(key)
            self.stopped.emit(key)
