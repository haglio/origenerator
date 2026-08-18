"""The gallery's search box: a line edit whose placeholder names what it covers.

The tree's selection is the search's scope, and the thing that says which folder
that is, is its whole path — a folder is named by a short code, and a code on its
own says nothing about which branch it sits in. So the box holds the full
breadcrumb and elides it from the left when the pane is too narrow for all of it:
the tail is the folder itself and its nearest parents, which is the half that
answers "search where?".
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit

# What the placeholder says around the path, and the room its own characters take.
_PREFIX = "Search "
_TRAILING = "…"
# Slack for the frame, the text margin and whatever padding the stylesheet adds:
# measured room that isn't accounted for reads as a path that fits when it
# doesn't, and the last few characters of the folder's own name are the ones
# that get clipped.
_CHROME = 12


class ScopeSearchEdit(QLineEdit):
    """A search box that says, in its placeholder, which folder a query would
    search — the whole path, elided from the left to whatever the box is wide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scope = ""
        self._render_placeholder()

    def set_scope(self, path: str):
        """Name the folder a query typed here would search."""
        if path != self._scope:
            self._scope = path
            self._render_placeholder()

    def scope(self) -> str:
        """The full, un-elided path the placeholder is showing some of."""
        return self._scope

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_placeholder()  # a wider pane shows more of the path

    def _render_placeholder(self):
        metrics = self.fontMetrics()
        room = (self.contentsRect().width() - _CHROME
                - metrics.horizontalAdvance(_PREFIX + _TRAILING))
        path = metrics.elidedText(self._scope, Qt.TextElideMode.ElideLeft,
                                  max(room, 0))
        # The trailing ellipsis is the "type here" one, and it goes when the path
        # is already wearing a leading one: two in a line read as a truncation at
        # both ends rather than as an invitation.
        tail = _TRAILING if path == self._scope else ""
        self.setPlaceholderText(f"{_PREFIX}{path}{tail}")
