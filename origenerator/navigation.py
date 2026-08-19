"""A browser-style back/forward history of the views the middle pane has shown.

Qt-free so the traversal logic stays unit-testable without a widget toolkit. The
gallery records every view the user lands on — a folder, a shelf (Recents,
Starred, ...), a search's results, and whichever item is picked in it — and
Back/Forward return to exactly that view, whether it was a generation reached by
an i2v's input-image link or the shelf they drilled from.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """One view of the middle pane, in the three parts it takes to rebuild it.

    A bare key would say only *where* the pane was pointed, which is not enough to
    return to what was on screen: the same shelf shows a different thing depending
    on which of its items is picked, and the same folder shows its search results
    instead while a query is running. All three parts together are what Back has
    to restore for it to land where the user actually was.
    """

    view: str            # the tree row the pane is drawn from: a folder or a shelf
    query: str = ""      # the search running over that row, if one is
    item: str | None = None  # the generation picked in it, if any


class NavigationHistory:
    """A cursor over a stack of visited locations.

    ``visit`` appends a new location and drops any forward history (a new branch);
    revisiting the current location is a no-op, so the gallery's refresh-driven
    re-selection of the same view never piles up duplicates. ``replace`` overwrites
    the current location instead, for a view that is being re-drawn rather than
    left. ``back`` and ``forward`` move the cursor and return the now-current
    location, or ``None`` at the respective end.
    """

    def __init__(self):
        self._stack: list[Location] = []
        self._index = -1

    def visit(self, location: Location):
        if self._stack and self._stack[self._index] == location:
            return
        del self._stack[self._index + 1:]  # a new branch discards the forward tail
        self._stack.append(location)
        self._index = len(self._stack) - 1

    def replace(self, location: Location):
        """Overwrite where the cursor stands, rather than stacking a stop on top.

        For a view being re-drawn in place — a query still being typed re-asks the
        same pane a dozen times, and each pause is not somewhere the user went.
        The forward tail goes all the same: what it branched from is no longer
        what is on screen.
        """
        if not self._stack:
            self.visit(location)
            return
        del self._stack[self._index + 1:]
        self._stack[self._index] = location

    def can_go_back(self) -> bool:
        return self._index > 0

    def can_go_forward(self) -> bool:
        return self._index < len(self._stack) - 1

    def back(self) -> Location | None:
        if not self.can_go_back():
            return None
        self._index -= 1
        return self._stack[self._index]

    def forward(self) -> Location | None:
        if not self.can_go_forward():
            return None
        self._index += 1
        return self._stack[self._index]

    def current(self) -> Location | None:
        return self._stack[self._index] if self._stack else None
