"""Keeps re-launching a settings folder's re-roll until the user stops it.

Auto-Generate is the gallery re-roll, again and again: each time a folder's
fresh variation finishes, launch another, until the user toggles it off or one
fails. This owns none of the generation machinery — it drives the existing
re-roll through an injected ``launch(key)`` and is told of each outcome via
:meth:`note_finished`/:meth:`note_canceled`/:meth:`note_failed`, so it stays free
of the view and the job internals and unit-tests without them.

Stopping is the user's word alone — :meth:`stop` (a stop asked of one folder)
and :meth:`stop_all` (the Auto toggle). Cancelling the variation being made is not that word: it
throws away *this seed*, which is what Auto-Generate's random seeds are for, so it
takes that as its cue to try another at once.

One folder at a time. Auto-Generate is a standing instruction to spend the whole
machine on one folder's settings, and two of them would only take turns at it —
each folder waiting out the other's render, both crawling. So turning it on
somewhere new is also how it is turned off where it was.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class AutoGenerateController(QObject):
    stopped = pyqtSignal(str)  # (folder key) a folder's Auto-Generate ended (stop or failure)

    def __init__(self, launch, parent=None):
        super().__init__(parent)
        self._launch = launch
        self._active: set[str] = set()

    def is_active(self, key: str) -> bool:
        return key in self._active

    def active_key(self) -> str | None:
        """The folder Auto-Generate runs in, or ``None`` — there is only ever one.

        What a surface asks when it has to say Auto-Generate is running
        *somewhere*: the switch lives on the folder in front, and an Auto-Generate
        the user has walked away from is exactly the one they need to be told about.
        """
        return next(iter(self._active), None)

    def start(self, key: str) -> None:
        """Auto-Generate in ``key``, ending it in whatever other folder it ran in.

        The hand-off happens only once the new folder's first variation is away:
        a launch that doesn't take leaves Auto-Generate where it was rather than
        stopping it in one folder and starting it in none. The folder it displaces reports
        through :attr:`stopped` exactly as a hand-stop would, so its switch is
        cleaned up the one way.
        """
        if key in self._active:
            return  # already auto-generating in this folder
        if not self._launch(key):
            return
        for other in list(self._active):
            self._end(other)
        self._active.add(key)

    def stop(self, key: str) -> None:
        """Stop a folder's Auto-Generate — the in-flight variation still lands, but no more
        are launched after it."""
        self._end(key)

    def note_finished(self, key: str) -> None:
        """A folder's re-roll finished — launch the next if Auto-Generate is still
        on, ending it if that next one can't start."""
        self._advance(key)

    def note_canceled(self, key: str) -> None:
        """A folder's re-roll was cancelled — try another seed straight away.

        Cancel means "not this one", not "stop": Auto-Generate's random seeds are
        exactly the place to throw one away, and having to re-arm Auto after every
        discard made the button fight the user. Only :meth:`stop`/:meth:`stop_all`
        end Auto-Generate.
        """
        self._advance(key)

    def note_failed(self, key: str) -> None:
        """A folder's re-roll failed — end Auto-Generate rather than spin on a broken
        workflow."""
        self._end(key)

    def stop_all(self) -> None:
        """End Auto-Generate wherever it is running."""
        for key in list(self._active):
            self._end(key)

    def _advance(self, key: str) -> None:
        """One variation ended without the user stopping Auto-Generate: launch the
        next if it is still on, ending it only if that next one can't start — an
        Auto-Generate with nothing running and nothing launchable is a dead one."""
        if key in self._active and not self._launch(key):
            self._end(key)

    def _end(self, key: str) -> None:
        if key in self._active:
            self._active.discard(key)
            self.stopped.emit(key)
