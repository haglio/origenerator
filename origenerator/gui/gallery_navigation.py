from __future__ import annotations

from contextlib import contextmanager
from typing import Protocol

from origenerator.navigation import Location, NavigationHistory


class NavigationHost(Protocol):
    def selected_folder_key(self) -> str | None: ...

    def selected_prompt_id(self) -> str | None: ...

    def pane_holds(self, prompt_id: str) -> bool: ...

    def show_folder(self, key: str) -> bool: ...

    def go_to_generation(self, prompt_id: str) -> None: ...

    def reveal(self, prompt_id: str) -> bool: ...

    def clear_selection(self) -> None: ...

    def nav_state_changed(self, can_go_back: bool, can_go_forward: bool) -> None: ...


class NavigationController:
    def __init__(self, host: NavigationHost, *, search):
        self._host = host
        self._search = search
        self._history = NavigationHistory()
        self._suppressed = False

    @property
    def suppressed(self) -> bool:
        return self._suppressed

    @contextmanager
    def off_the_record(self):
        was = self._suppressed
        self._suppressed = True
        try:
            yield
        finally:
            self._suppressed = was

    def seed(self) -> None:
        if self._history.current() is not None:
            return
        location = self._current_location()
        if location is not None:
            self._history.visit(location)
            self._sync_buttons()

    def record(self, item: str | None = None) -> None:
        if self._suppressed:
            return
        view = self._host.selected_folder_key()
        if view is None:
            return
        location = Location(view, self._search.query, item, self._search.everywhere)
        current = self._history.current()
        if self._redrawing_the_same_search(location, current):
            if (current.query, current.everywhere) == (location.query, location.everywhere):
                return
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
        view = self._host.selected_folder_key()
        if view is None:
            return None
        item = self._host.selected_prompt_id()
        if item is not None and not self._host.pane_holds(item):
            item = None
        return Location(view, self._search.query, item, self._search.everywhere)

    def _restore(self, location: Location) -> None:
        with self.off_the_record():
            self._search.restore(location.query, location.everywhere)
            if not self._host.show_folder(location.view):
                if location.item is not None:
                    self._host.go_to_generation(location.item)
                return
            if location.query:
                self._search.run()
            if location.item is not None:
                self._reveal_in_pane(location.item)
            else:
                self._host.clear_selection()

    def _reveal_in_pane(self, prompt_id: str) -> None:
        if self._host.pane_holds(prompt_id):
            self._host.reveal(prompt_id)

    def _sync_buttons(self) -> None:
        self._host.nav_state_changed(
            self._history.can_go_back(), self._history.can_go_forward())

    @staticmethod
    def _redrawing_the_same_search(location: Location, current: Location | None) -> bool:
        return bool(location.query and location.item is None
                    and current is not None and current.query
                    and current.view == location.view)
