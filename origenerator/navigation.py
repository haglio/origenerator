"""A browser-style back/forward history of visited locations.

Qt-free so the traversal logic stays unit-testable without a widget toolkit. The
gallery records each location the user opens — a generation or a shelf (Recents,
Starred) — and lets Back/Forward return to where they just were, whether that was
a generation reached by an i2v's input-image link or the shelf they drilled from.
"""


class NavigationHistory:
    """A cursor over a stack of visited locations (opaque string keys).

    ``visit`` appends a new location and drops any forward history (a new branch);
    revisiting the current location is a no-op, so the gallery's refresh-driven
    re-selection of the same generation never piles up duplicates. ``back`` and
    ``forward`` move the cursor and return the now-current location, or ``None`` at
    the respective end.
    """

    def __init__(self):
        self._stack: list[str] = []
        self._index = -1

    def visit(self, location: str):
        if self._stack and self._stack[self._index] == location:
            return
        del self._stack[self._index + 1:]  # a new branch discards the forward tail
        self._stack.append(location)
        self._index = len(self._stack) - 1

    def can_go_back(self) -> bool:
        return self._index > 0

    def can_go_forward(self) -> bool:
        return self._index < len(self._stack) - 1

    def back(self) -> str | None:
        if not self.can_go_back():
            return None
        self._index -= 1
        return self._stack[self._index]

    def forward(self) -> str | None:
        if not self.can_go_forward():
            return None
        self._index += 1
        return self._stack[self._index]

    def current(self) -> str | None:
        return self._stack[self._index] if self._stack else None
