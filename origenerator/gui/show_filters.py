"""What a show may play: all of it, the favorites, the enhanced ones, or both.

A show is usually the whole of what is in front of you — a folder, a shelf, a
search's hits — and most of the time that is what you want. Two things narrow it.

A folder enhanced through carries both versions of everything: the render and the
better one made from it. Sitting through a pass of that is every picture twice,
the second time being the point. And a folder you have been through once has
stars on the ones worth coming back to, which is a different question again:
not "which of these came out best" but "which did I keep".

Both are app-wide, for the same reason the pace is: the console that carries
their switches is app-wide. Turned on in the main window they are what the next
show opens with; turned on over a running show they narrow that show where it
stands.

They narrow what a SHOW plays and nothing else. The gallery goes on listing
everything, because a filter that also emptied the folder behind you would be a
different feature wearing one switch — and in there an enhancement is not a
second row anyway, it is a level stacked on the one it came from.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import gallery


class ShowFilters(QObject):
    """The two narrowing switches, and word when either moves.

    One signal for both: everything that reacts — the console's own drawing, the
    Slideshow button, an open show — reacts to the same thing either way, which
    is that what there is to play has changed.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enhanced = False
        self._favorites = False

    @property
    def enhanced(self) -> bool:
        return self._enhanced

    @property
    def favorites(self) -> bool:
        return self._favorites

    @property
    def any_on(self) -> bool:
        return self._enhanced or self._favorites

    def set_enhanced(self, on: bool) -> None:
        self._set(enhanced=bool(on), favorites=self._favorites)

    def set_favorites(self, on: bool) -> None:
        self._set(enhanced=self._enhanced, favorites=bool(on))

    def toggle_enhanced(self) -> None:
        self.set_enhanced(not self._enhanced)

    def toggle_favorites(self) -> None:
        self.set_favorites(not self._favorites)

    def clear(self) -> None:
        """Everything back — the way out of both at once, which is what "clear
        filter" has to mean once there is more than one of them to clear."""
        self._set(enhanced=False, favorites=False)

    def _set(self, *, enhanced: bool, favorites: bool) -> None:
        if (enhanced, favorites) == (self._enhanced, self._favorites):
            return
        self._enhanced, self._favorites = enhanced, favorites
        self.changed.emit()

    def keeps(self, row: dict) -> bool:
        """Whether ``row`` survives the switches that are on.

        Both at once is an and, not an or: two narrowings asked for together
        mean the ones that answer both, the way every other pair of filters in
        this family stacks.
        """
        if self._enhanced and not gallery.is_enhanced_row(row):
            return False
        if self._favorites and not row.get("starred"):
            return False
        return True
