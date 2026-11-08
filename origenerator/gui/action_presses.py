from __future__ import annotations

from collections.abc import Callable

from funestra.loop_cycle import SEED

from origenerator import said_action
from origenerator.gui.message import INFO, WARNING
from origenerator.gui.slideshow_set import (
    SlideshowSet,
    narrow_to_actions,
    narrow_to_the_action_on_screen,
)
from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.outside_videos import places_here
from origenerator.sent_back import SentBack, the_librarys
from origenerator.slideshow import Slide

NO_ACTION_TO_REMOVE = "No action to remove"
SENT_BACK = "Sent back to the action setter tool"


class ActionPresses:
    def __init__(self, the_set: Callable[[], SlideshowSet],
                 the_actions: Callable[[], SlideshowActions], *, flash: Callable[..., None],
                 jump_to: Callable[[object], None], loop: Callable[[str], None]) -> None:
        self._the_set = the_set
        self._the_actions = the_actions
        self._flash = flash
        self._jump_to = jump_to
        self._loop = loop

    def filter(self, query: str) -> None:
        playing = self._the_set()
        row = playing.configuration_row(query)
        if row is not None:
            if row is not playing.playlist.current():
                self._jump_to(row)
            self._loop(SEED)
            return
        self._tell(narrow_to_actions(playing, query))

    def filter_to_the_one_on_screen(self) -> None:
        self._tell(narrow_to_the_action_on_screen(self._the_set()))

    def strike_the_one_on_screen(self) -> None:
        playing, strike = self._the_set(), self._the_actions().strike_action
        on_screen = playing.playlist.current()
        struck = strike(on_screen) if strike is not None and on_screen is not None else ""
        if not struck:
            self._tell((NO_ACTION_TO_REMOVE, False))
            return
        playing.library_moved()
        self._tell((SENT_BACK, True))

    def _tell(self, how_it_went: tuple[str, bool]) -> None:
        said, done = how_it_went
        self._flash(said, kind=INFO if done else WARNING)


def striking(db, gallery, places_here=places_here,
             sent_back: Callable[[], SentBack] = the_librarys) -> Callable[[Slide], str]:
    def strike(slide) -> str:
        struck = said_action.strike(db, slide, places_here, sent_back())
        if struck:
            gallery.refresh()
        return struck

    return strike
