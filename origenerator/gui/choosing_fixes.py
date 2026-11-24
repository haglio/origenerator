from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from origenerator.fixes_being_chosen import FixesBeingChosen

RESTS_AFTER_MS = 2000
LONGEST_WAIT_FOR_THE_POINTER_MS = 30_000


class ChoosingFixes(QObject):
    def __init__(self, fixes: FixesBeingChosen, *, db, tabs, slideshows,
                 read_the_gallery_again: Callable[[], None], parent: QObject):
        super().__init__(parent)
        self._fixes = fixes
        self._db = db
        self._tabs = tabs
        self._slideshows = slideshows
        self._read_the_gallery_again = read_the_gallery_again
        self._waited_for_the_pointer_ms = 0
        self.rest = QTimer(self)
        self.rest.setSingleShot(True)
        self.rest.setInterval(RESTS_AFTER_MS)
        self.rest.timeout.connect(self._record_once_the_image_is_written)

    def change(self, prompt_id: str, filename: str, part: str, what: str, to: bool) -> None:
        row = self._db.get_generation(prompt_id)
        shown = self._fixes.change(row, filename, part, what, to) if row is not None else None
        self._tabs.show_fixes_changed(prompt_id, filename, shown)
        if shown is not None:
            self._waited_for_the_pointer_ms = 0
            self.rest.start()

    def settle(self) -> None:
        self.rest.stop()
        self._show_recorded(self._fixes.settle())

    def settled_before(self, ask: Callable) -> Callable:
        def settled_then(*asked):
            self.settle()
            return ask(*asked)
        return settled_then

    def close(self) -> None:
        self.rest.stop()
        self._fixes.settle()

    def _record_once_the_image_is_written(self) -> None:
        if self._fixes.any_being_written() or self._the_pointer_is_still_on_the_fixes():
            self.rest.start()
            return
        self._show_recorded(self._fixes.record())

    def _the_pointer_is_still_on_the_fixes(self) -> bool:
        if (self._waited_for_the_pointer_ms >= LONGEST_WAIT_FOR_THE_POINTER_MS
                or not self._tabs.pointer_is_on_the_fixes()):
            return False
        self._waited_for_the_pointer_ms += self.rest.interval()
        return True

    def _show_recorded(self, prompt_ids: list[str]) -> None:
        if not prompt_ids:
            return
        self._read_the_gallery_again()
        for prompt_id in prompt_ids:
            recorded = self._db.get_generation(prompt_id)
            if recorded is not None:
                self._tabs.take_fixes_recorded(recorded)
                self._slideshows.note_versions_deleted(recorded)
