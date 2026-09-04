"""Find-in-prompts: walking the words of a config tab's prompt fields.

The TOC's own find narrows the folder tree to folders; this is the other kind —
the browser-style find *inside* what is on screen. A prompt runs to hundreds of
words and every folder name of it is a 60-character headline, so the only way to
locate a word you wrote is to search the field itself.

This holds the matches, paints them, and walks between them.
:class:`~origenerator.gui.find_bar.FindBar` is the strip of controls that drives
it; neither knows about the other, and the gallery view wires the two together.
"""

from PyQt6.QtGui import QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QScrollArea, QTextEdit

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.deferred import defer
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import AMBER, BG_PRIMARY, BLUE, TEXT_PRIMARY

# Every hit wears the dim blue and the one you're standing on wears amber, so
# stepping reads as a cursor moving through the matches rather than as the set of
# them changing under you.
_MATCH_BG = BLUE.darker(150)
_CURRENT_BG = AMBER
# Vertical breathing room around a field a step scrolls to, so the match lands
# among its neighbors instead of flush against the edge of the pane.
_REVEAL_MARGIN = 40


def _unfold(widget):
    """Open the collapsible section a field sits in, if it's folded shut.

    The Foley prompts live in a section that starts closed, and a match inside a
    closed section is one the user is told about but can't be shown.
    """
    node = widget.parent()
    while node is not None:
        if isinstance(node, CollapsibleSection):
            node.set_collapsed(False)
            return
        node = node.parent()


def _scroll_into_view(widget):
    """Scroll the form's own scroll area to ``widget``, so a match in a prompt far
    down a long form is on screen rather than merely selected off it."""
    node = widget.parent()
    while node is not None:
        if isinstance(node, QScrollArea):
            node.ensureWidgetVisible(widget, 0, _REVEAL_MARGIN)
            return
        node = node.parent()


class PromptFind:
    """One query's matches across a set of prompt fields, and where in them you
    are standing.

    Plain case-insensitive substring, non-overlapping — what someone reaching for
    Ctrl+F to find a word they wrote means, with no pattern syntax to get wrong.
    """

    def __init__(self):
        self._fields: list = []
        self._matches: list[tuple] = []  # (field, position), fields in form order
        self._index = -1                 # the current match; -1 when there are none
        self._query = ""

    # --- what is being searched ---------------------------------------------

    def set_fields(self, fields) -> int:
        """Aim the find at ``fields`` — a tab's prompt inputs, in form order —
        dropping the highlights the previous set is still wearing.

        Called whenever the front tab changes or its form is swapped out, and the
        old widgets are still alive at that moment (Qt defers their deletion), so
        this is also what keeps the paint from outliving them.
        """
        self._paint([])
        self._fields = list(fields)
        return self._run(reset=True)

    # --- searching ------------------------------------------------------------

    def search(self, query: str) -> int:
        """Run ``query`` and land on its first match — shown, not merely counted.
        Returns how many there are."""
        self._query = query
        total = self._run(reset=True)
        if self._matches:
            self._reveal()
        return total

    def refresh(self) -> int:
        """Re-run the standing query over text that changed underneath it — the
        user editing a prompt with the find open — keeping the place in the results
        rather than snapping back to the first, so the view doesn't jump as they
        type."""
        return self._run(reset=False)

    def _run(self, *, reset: bool) -> int:
        previous = self._index
        self._matches = self._collect()
        if not self._matches:
            self._index = -1
        elif reset or previous < 0:
            self._index = 0
        else:
            self._index = min(previous, len(self._matches) - 1)
        self._paint(self._matches)
        return len(self._matches)

    def _collect(self) -> list[tuple]:
        query = self._query.lower()
        if not query:
            return []
        found = []
        for field in self._fields:
            text = field.toPlainText().lower()
            at = text.find(query)
            while at >= 0:
                found.append((field, at))
                at = text.find(query, at + len(query))
        return found

    # --- walking the matches --------------------------------------------------

    def count(self) -> int:
        return len(self._matches)

    def position(self) -> int:
        """Which match is current, counting from one; 0 when there are none."""
        return self._index + 1 if self._index >= 0 else 0

    def step(self, delta: int):
        """Move ``delta`` matches along, wrapping at either end, and show where you
        land: its section unfolded, the field scrolled to, the hit selected."""
        if not self._matches:
            return
        self._index = (self._index + delta) % len(self._matches)
        self._paint(self._matches)
        self._reveal()

    def clear(self):
        """End the search: no query, no matches, and no paint left behind in the
        prompts."""
        self._query = ""
        self._matches = []
        self._index = -1
        self._paint([])

    # --- showing them ---------------------------------------------------------

    def _reveal(self):
        field, at = self._matches[self._index]
        _unfold(field)
        # The cursor lands on the match but selects nothing. Selecting it would
        # read better — the word there to type over — except that Qt paints a real
        # selection *over* an extra selection in the palette's highlight color, so
        # the amber would never be seen and which match is current would come down
        # to whatever that palette happens to be (measured: it does exactly that).
        field.setTextCursor(self._cursor(field, at, select=False))
        field.ensureCursorVisible()
        _scroll_into_view(field)
        # A section unfolded a line ago hasn't been laid out yet, so that scroll
        # aimed at where the field used to be. Aim again once this turn's layout
        # has run — owned by the field, since a tab closing before then takes the
        # field with it and there is nothing left to scroll to.
        defer(field, lambda: self._reapply_reveal(field))

    def _reapply_reveal(self, field):
        try:
            _scroll_into_view(field)
        except RuntimeError:
            pass  # the field's tab was closed before the layout it was waiting on

    def _paint(self, matches):
        for field in self._fields:
            field.setExtraSelections([
                self._selection(field, at, current=(i == self._index))
                for i, (owner, at) in enumerate(matches) if owner is field
            ])

    def _selection(self, field, at: int, *, current: bool):
        selection = QTextEdit.ExtraSelection()
        selection.cursor = self._cursor(field, at)
        style = QTextCharFormat()
        style.setBackground(_CURRENT_BG if current else _MATCH_BG)
        style.setForeground(BG_PRIMARY if current else TEXT_PRIMARY)
        selection.format = style
        return selection

    def _cursor(self, field, at: int, *, select: bool = True) -> QTextCursor:
        cursor = QTextCursor(field.document())
        cursor.setPosition(at)
        if select:
            cursor.setPosition(at + len(self._query), QTextCursor.MoveMode.KeepAnchor)
        return cursor
