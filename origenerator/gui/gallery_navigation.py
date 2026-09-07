"""Back and Forward across the gallery: what was on screen, and getting there.

The second of the gallery's screen concerns to come out of the view that used to
hold all of them. What lives here is a stop's whole life — recording one when a
gesture puts something on screen, collapsing the redraws that are not
navigations, walking the trail either way, and re-showing a stop as it stood.

The suppression flag lives here too, and only here. It used to be a bare boolean
on the view that four unrelated paths set and cleared by hand, each having to
remember to restore rather than clear it; it is a context manager now, and what
it means — this move walks history rather than adds to it — is stated once.

What stays with the host is what a stop is *of*: which folder the tree has
selected, what the pane is showing, and how to get somewhere. :class:`NavigationHost`
names each of those.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Protocol

from origenerator.navigation import Location, NavigationHistory


class NavigationHost(Protocol):
    """What a history needs of the gallery around it, and nothing else."""

    def selected_folder_key(self) -> str | None:
        """The folder or shelf the tree has selected, or ``None`` with nothing
        open at all."""

    def selected_prompt_id(self) -> str | None:
        """The generation picked in the pane, or ``None``."""

    def pane_holds(self, prompt_id: str) -> bool:
        """Whether the pane has a tile for this generation right now."""

    def show_folder(self, key: str) -> bool:
        """Draw the folder or shelf ``key`` names, returning whether the tree
        had a row for it — a stop whose folder a delete emptied has none."""

    def go_to_generation(self, prompt_id: str) -> None:
        """Open whatever holds this generation and land on it — the fallback
        when a stop's own folder is gone."""

    def reveal(self, prompt_id: str) -> None:
        """Pick and scroll to a tile the pane is already showing."""

    def clear_selection(self) -> None:
        """Put the selection down: nothing was picked at this stop."""

    def nav_state_changed(self, can_go_back: bool, can_go_forward: bool) -> None:
        """The Back and Forward buttons fit the trail as it now stands."""


class NavigationController:
    """The back/forward trail, and the one way onto and off it."""

    def __init__(self, host: NavigationHost, *, search):
        self._host = host
        self._search = search
        self._history = NavigationHistory()
        # True while a rebuild or a Back/Forward is what re-selected something:
        # those move within history rather than onto it.
        self._suppressed = False

    @property
    def suppressed(self) -> bool:
        """Whether the move in hand is one history should not record — read by
        the few places that have their own reason to skip work under it."""
        return self._suppressed

    @contextmanager
    def off_the_record(self):
        """Hold the trail still for a move that is a step on the way rather than
        somewhere the user went. Restores rather than clears, so a nested move
        does not hand the trail back early."""
        was = self._suppressed
        self._suppressed = True
        try:
            yield
        finally:
            self._suppressed = was

    def seed(self) -> None:
        """Record wherever the gallery first lands, once, so Back works even if
        the user's very first move leaves it."""
        if self._history.current() is not None:
            return
        location = self._current_location()
        if location is not None:
            self._history.visit(location)
            self._sync_buttons()

    def record(self, item: str | None = None) -> None:
        """Record what the middle pane now shows: the folder or shelf the tree has
        selected, the query running over it, and ``item`` if the gesture picked one.

        Skipped while a rebuild or Back/Forward is what put it there. Everything
        the pane can show is recorded the same way, so Back returns to the view
        the user was actually looking at, whatever kind of view it was.
        """
        if self._suppressed:
            return
        view = self._host.selected_folder_key()
        if view is None:
            return  # nothing open: no view to come back to
        location = Location(view, self._search.query, item)
        current = self._history.current()
        if self._redrawing_the_same_search(location, current):
            # A search results pane redraws for reasons that are not navigations —
            # a sort, a widening landing, a generation finishing under a poll — and
            # a stop per redraw would fill history with the pane already on screen.
            if current.query == location.query:
                return
            # A query being narrowed is that same pane re-asked rather than another
            # one opened, so each pause overwrites its stop instead of adding one.
            self._history.replace(location)
        else:
            self._history.visit(location)
        self._sync_buttons()

    def go_back(self) -> None:
        self._walk(self._history.back())

    def go_forward(self) -> None:
        self._walk(self._history.forward())

    def _walk(self, location: Location | None) -> None:
        if location is not None:
            self._restore(location)
        self._sync_buttons()

    def _current_location(self) -> Location | None:
        """What the middle pane is showing right now, as a history stop: the tree
        row it is drawn from, any query running over it, and the item picked in it
        (``None`` with nothing open at all).

        Only for seeding history at startup, where there is no gesture to ask.
        Every stop after that is recorded by the gesture that made it, which knows
        which item it picked — see :meth:`record`.
        """
        view = self._host.selected_folder_key()
        if view is None:
            return None
        item = self._host.selected_prompt_id()
        if item is not None and not self._host.pane_holds(item):
            item = None  # left by the pane this one replaced
        return Location(view, self._search.query, item)

    def _restore(self, location: Location) -> None:
        """Re-show a stop as it stood — its folder or shelf, the query that was
        running over it, and the item that was picked in it — without recording the
        move (which walks history rather than adding to it).

        A stop whose row the tree no longer has (a folder emptied by a delete)
        falls back to showing its item wherever it now lives, rather than leaving
        the press doing nothing at all.
        """
        with self.off_the_record():
            self._search.restore(location.query)
            if not self._host.show_folder(location.view):
                if location.item is not None:
                    self._host.go_to_generation(location.item)
                return
            if location.query:
                self._search.run()  # takes the pane back off the folder again
            if location.item is not None:
                self._reveal_in_pane(location.item)
            else:
                # Nothing was picked at this stop, so nothing is picked on landing:
                # a folder still showing the item Back just left would look like the
                # press had done nothing at all.
                self._host.clear_selection()

    def _reveal_in_pane(self, prompt_id: str) -> None:
        """Land on an item the pane is already showing. Silent if the pane has no
        tile for it — a Recents page not drawn yet, a row since deleted — which
        leaves the view itself restored rather than jumping somewhere else."""
        if self._host.pane_holds(prompt_id):
            self._host.reveal(prompt_id)

    def _sync_buttons(self) -> None:
        self._host.nav_state_changed(
            self._history.can_go_back(), self._history.can_go_forward())

    @staticmethod
    def _redrawing_the_same_search(location: Location, current: Location | None) -> bool:
        """Whether ``location`` is the search stop at ``current`` being drawn again
        rather than somewhere new: the same folder, a query over it either way, and
        no item picked (picking a hit is a step within the results, not a redraw of
        them)."""
        return bool(location.query and location.item is None
                    and current is not None and current.query
                    and current.view == location.view)
