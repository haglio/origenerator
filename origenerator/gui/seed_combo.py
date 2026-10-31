from __future__ import annotations

from collections.abc import Callable
from itertools import groupby
from operator import attrgetter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from origenerator.gui.thumbnail_dropdown import (
    THUMBNAILS_ROLE,
    ThumbnailDropdown,
    thumbnail_of,
    unmade_thumbnail,
)
from origenerator.seed_history import SeedUse

_TALLEST_ROW_A_LIST_LAYS_OUT = 32767


class SeedComboBox(ThumbnailDropdown):
    def __init__(self, history: Callable[[], list[SeedUse]],
                 looping_preview: Callable[[str], str | None], parent=None):
        super().__init__(parent, looping_preview=looping_preview)
        self._history = history
        self._item: SeedUse | None = None
        self._tab_size: tuple[int, int] | None = None
        self._picked: SeedUse | None = None
        self.setEditable(True)
        self.setCompleter(None)
        self._thumbnail = QLabel(self)
        self._thumbnail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editTextChanged.connect(self._refresh_thumbnail)
        self.activated.connect(self._remember_pick)
        self._refresh_thumbnail()

    def describe(self, item_seed: int | None, item_thumbnail: str | None,
                 tab_size: tuple[int, int] | None) -> None:
        self._item = (SeedUse(item_seed, item_thumbnail)
                      if item_seed is not None and item_thumbnail else None)
        self._tab_size = tab_size
        self._refresh_thumbnail()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_thumbnail()

    def _thumbnail_side(self) -> int:
        return max(12, self.height() - 6)

    def _place_thumbnail(self) -> None:
        side = self._thumbnail_side()
        self._thumbnail.setGeometry(self.lineEdit().x() + 1, (self.height() - side) // 2, side, side)
        self._thumbnail.raise_()
        self.lineEdit().setTextMargins(side + 4, 0, 0, 0)

    def _remember_pick(self, row: int) -> None:
        self._picked = self.itemData(row, THUMBNAILS_ROLE)[0]
        self._refresh_thumbnail()

    def _refresh_thumbnail(self, *_) -> None:
        side = self._thumbnail_side()
        use = self._use_the_field_shows()
        thumbnail = thumbnail_of(use, side) if use is not None else None
        self._thumbnail.setPixmap(
            thumbnail or unmade_thumbnail(side, use.size if use is not None else self._tab_size))
        self._place_thumbnail()

    def _use_the_field_shows(self) -> SeedUse | None:
        return next((use for use in (self._picked, self._item)
                     if use is not None and str(use.seed) == self.currentText()), None)

    def showPopup(self):
        seed = self.currentText()
        blocked = self.blockSignals(True)
        self._list_rows(self._rows_of(self._history()))
        self.setEditText(seed)
        self.blockSignals(blocked)
        super().showPopup()

    def _rows_of(self, uses: list[SeedUse]):
        most_in_a_row = max(1, _TALLEST_ROW_A_LIST_LAYS_OUT // self._thumbnail_row_height())
        for seed, grouped in groupby(uses, key=attrgetter("seed")):
            stretch = tuple(grouped)
            for start in range(0, len(stretch), most_in_a_row):
                yield str(seed), stretch[start:start + most_in_a_row]
