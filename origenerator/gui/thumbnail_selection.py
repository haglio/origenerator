"""Which thumbnails are picked, and what a click with a modifier does to that.

Pure list-and-set logic, lifted out of the pane that draws the tiles. Three of the
pane's sixteen fields were this -- what is on screen in the order it is shown,
which of those are picked, and the tile a Shift-click measures its run from -- and
the rule between them is a file browser's: Ctrl toggles one, Shift extends a
contiguous run from the anchor, a plain click resets to one.

No Qt here on purpose. The pane turns the held modifiers into two booleans and
this decides, so the rule is exercisable with a list of strings -- which the
pane's own suite could not do while the set, the anchor and the order all lived
among its widgets.
"""
from __future__ import annotations


class ThumbnailSelection:
    """The picked set, the anchor a run is measured from, and the shown order."""

    def __init__(self):
        self._picked: set[str] = set()
        self._anchor: str | None = None
        # Generations on screen, in the order they are shown: what a Shift-click
        # measures its run along, and the order the picked ones are reported in.
        self._shown: list[str] = []

    # --- what is on screen ---------------------------------------------------

    def note_shown(self, prompt_id: str) -> None:
        """One more tile drawn, at the end of what is on screen."""
        self._shown.append(prompt_id)

    def forget_what_was_shown(self) -> None:
        """The pane is being redrawn: nothing is on screen until it is drawn again.

        The picked set is dropped separately (see :meth:`clear`), because an empty
        pane and a pane with nothing picked in it are different things: the pane
        is emptied by one renderer and refilled by the next within the same
        gesture.
        """
        self._shown = []

    @property
    def shown(self) -> list[str]:
        """What is on screen, in the order it is shown."""
        return list(self._shown)

    # --- what is picked ------------------------------------------------------

    def apply(self, prompt_id: str, *, ctrl: bool = False, shift: bool = False) -> None:
        """Pick ``prompt_id`` the way the held modifiers dictate.

        Ctrl toggles that one tile; Shift extends a contiguous run from the
        anchor; a plain click resets to just this tile. Mirrors a typical file
        browser.

        A Shift-click whose anchor is no longer on screen -- a pane redrawn under
        it, a shelf paged on -- has no run to measure, so it lands as a plain
        click rather than as a range from nowhere.
        """
        if ctrl:
            self._picked ^= {prompt_id}
            self._anchor = prompt_id
            return
        if shift and self._anchor in self._shown and prompt_id in self._shown:
            a = self._shown.index(self._anchor)
            b = self._shown.index(prompt_id)
            lo, hi = sorted((a, b))
            self._picked = set(self._shown[lo:hi + 1])
            return
        self._picked = {prompt_id}
        self._anchor = prompt_id

    def clear(self) -> None:
        """Nothing picked, and no run to extend."""
        self._picked = set()
        self._anchor = None

    def holds(self, prompt_id: str) -> bool:
        """Whether this tile is one of the picked — what a right-click asks before
        narrowing to the tile under the pointer."""
        return prompt_id in self._picked

    @property
    def picked(self) -> set[str]:
        """The picked tiles, unordered. Read by the buttons that count them."""
        return self._picked

    def in_shown_order(self) -> list[str]:
        """The picked tiles in the order the pane shows them — what an act on a
        whole selection runs through, so it runs in the order the user sees."""
        return [pid for pid in self._shown if pid in self._picked]
