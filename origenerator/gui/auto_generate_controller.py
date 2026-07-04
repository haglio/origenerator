"""Keeps re-launching a settings folder's re-roll until the user stops it.

"Repeatedly generate in a folder" is the gallery re-roll on a loop: each time a
folder's fresh variation finishes, launch another, until the user toggles it off
or one fails. This owns none of the generation machinery — it drives the existing
re-roll through an injected ``launch(key)`` and is told of each outcome via
:meth:`note_finished`/:meth:`note_failed`, so it stays free of the view and the
job internals and unit-tests without them.
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
        if key in self._active and not self._launch(key):
            self._end(key)

    def note_failed(self, key: str) -> None:
        """A folder's re-roll failed — end the loop rather than spin on a broken
        workflow."""
        self._end(key)

    def _end(self, key: str) -> None:
        if key in self._active:
            self._active.discard(key)
            self.stopped.emit(key)
