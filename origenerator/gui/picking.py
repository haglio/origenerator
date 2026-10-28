"""Which entries of a list are picked -- the gallery's thumbnails, an image's
versions -- and what a click with a modifier does to that.

Pure list-and-set logic, lifted out of the pane that draws the tiles. Three of the
pane's sixteen fields were this -- what it lists in the order it shows them,
which of those are picked, and the tile a Shift-click measures its run from -- and
the rule between them is a file browser's: Ctrl toggles one, Shift extends a
contiguous run from the anchor, a plain click resets to one.

No Qt here on purpose. The pane turns the held modifiers into two booleans and
this decides, so the rule is exercisable with a list of strings -- which the
pane's own suite could not do while the set, the anchor and the order all lived
among its widgets.
"""
from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass


@dataclass(frozen=True)
class Picks:
    picked: frozenset[Hashable] = frozenset()
    anchor: Hashable | None = None


class Picking:
    """The picked set, the anchor a run is measured from, and the shown order."""

    def __init__(self):
        self._picked: set[Hashable] = set()
        self._anchor: Hashable | None = None
        # Every entry listed, in the order shown, drawn yet or not: what a Shift-click
        # measures its run along, and the order the picked ones are reported in.
        self._shown: list[Hashable] = []

    # --- what is listed -------------------------------------------------------

    def note_shown(self, entry: Hashable) -> None:
        """One more entry, at the end of what is listed."""
        self._shown.append(entry)

    def forget_what_was_shown(self) -> None:
        """The pane is being redrawn: it lists nothing until it is drawn again.

        The picked set is dropped separately (see :meth:`clear`), because an empty
        pane and a pane with nothing picked in it are different things: the pane
        is emptied by one renderer and refilled by the next within the same
        gesture.
        """
        self._shown = []

    @property
    def shown(self) -> list[Hashable]:
        """What is listed, in the order it is shown."""
        return list(self._shown)

    # --- what is picked ------------------------------------------------------

    def apply(self, entry: Hashable, *, ctrl: bool = False, shift: bool = False) -> None:
        """Pick ``entry`` the way the held modifiers dictate.

        Ctrl toggles that one entry; Shift extends a contiguous run from the
        anchor; a plain click resets to just this entry. Mirrors a typical file
        browser.

        A Shift-click whose anchor is no longer listed -- a pane redrawn under
        it -- has no run to measure, so it lands as a plain click rather than as
        a range from nowhere.
        """
        if ctrl:
            self._picked ^= {entry}
            self._anchor = entry
            return
        if shift and self._anchor in self._shown and entry in self._shown:
            a = self._shown.index(self._anchor)
            b = self._shown.index(entry)
            lo, hi = sorted((a, b))
            self._picked = set(self._shown[lo:hi + 1])
            return
        self._picked = {entry}
        self._anchor = entry

    def clear(self) -> None:
        """Nothing picked, and no run to extend."""
        self._picked = set()
        self._anchor = None

    def picks(self) -> Picks:
        return Picks(frozenset(self._picked), self._anchor)

    def pick_again(self, picks: Picks) -> None:
        self._picked = set(picks.picked) & set(self._shown)
        self._anchor = picks.anchor

    def holds(self, entry: Hashable) -> bool:
        """Whether this entry is one of the picked — what a right-click asks
        before narrowing to the entry under the pointer."""
        return entry in self._picked

    @property
    def picked(self) -> set[Hashable]:
        """The picked entries, unordered. Read by the buttons that count them."""
        return self._picked

    def in_shown_order(self) -> list[Hashable]:
        """The picked entries in the order they are shown — what an act on a whole
        selection runs through, so it runs in the order the user sees."""
        return [entry for entry in self._shown if entry in self._picked]
