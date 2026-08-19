"""Whether a show plays only the pictures that have been enhanced.

A show is usually the whole of what is in front of you — a folder, a shelf, a
search's hits — and most of the time that is what you want. But a folder that has
been enhanced through carries both versions of everything: the render and the
better one made from it. Sitting through a pass of that is sitting through each
picture twice, the second time being the point.

So this is one switch over what a show may play, and it is app-wide for the same
reason the pace is: the console that carries it is app-wide. Turned on in the
main window it is what the next show opens with; turned on over a running show it
narrows that show where it stands.

It narrows what a SHOW plays and nothing else. The gallery goes on listing
everything, because a filter that also emptied the folder behind you would be a
different feature wearing one switch — and the enhanced picture and the render it
came from are one row in there anyway, with the levels stacked on it.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class EnhancedFilter(QObject):
    """The enhanced-only switch, and word when it moves."""

    changed = pyqtSignal(bool)

    def __init__(self, active: bool = False, parent=None):
        super().__init__(parent)
        self._active = bool(active)

    @property
    def active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._active:
            self._active = active
            self.changed.emit(active)

    def toggle(self) -> None:
        self.set_active(not self._active)
