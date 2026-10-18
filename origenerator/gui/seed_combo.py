from __future__ import annotations

from collections.abc import Callable
from itertools import groupby
from operator import attrgetter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from origenerator.gui.pictured_dropdown import (
    PICTURES_ROLE,
    PicturedDropdown,
    picture_of,
    unmade_cell,
)
from origenerator.seed_history import SeedUse

_TALLEST_ROW_A_LIST_LAYS_OUT = 32767


class SeedComboBox(PicturedDropdown):
    def __init__(self, history: Callable[[], list[SeedUse]], parent=None):
        super().__init__(parent)
        self._history = history
        self._item: SeedUse | None = None
        self._tab_size: tuple[int, int] | None = None
        self._picked: SeedUse | None = None
        self.setEditable(True)
        self.setCompleter(None)
        self._picture = QLabel(self)
        self._picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.editTextChanged.connect(self._refresh_picture)
        self.activated.connect(self._remember_pick)
        self._refresh_picture()

    def describe(self, item_seed: int | None, item_thumbnail: str | None,
                 tab_size: tuple[int, int] | None) -> None:
        self._item = (SeedUse(item_seed, item_thumbnail)
                      if item_seed is not None and item_thumbnail else None)
        self._tab_size = tab_size
        self._refresh_picture()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_picture()

    def _picture_side(self) -> int:
        return max(12, self.height() - 6)

    def _place_picture(self) -> None:
        side = self._picture_side()
        self._picture.setGeometry(self.lineEdit().x() + 1, (self.height() - side) // 2, side, side)
        self._picture.raise_()
        self.lineEdit().setTextMargins(side + 4, 0, 0, 0)

    def _remember_pick(self, row: int) -> None:
        self._picked = self.itemData(row, PICTURES_ROLE)[0]
        self._refresh_picture()

    def _refresh_picture(self, *_) -> None:
        side = self._picture_side()
        use = self._use_the_field_shows()
        picture = picture_of(use, side) if use is not None else None
        self._picture.setPixmap(
            picture or unmade_cell(side, use.size if use is not None else self._tab_size))
        self._place_picture()

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
        most_in_a_row = max(1, _TALLEST_ROW_A_LIST_LAYS_OUT // self._pitch())
        for seed, stretch in groupby(uses, key=attrgetter("seed")):
            stretch = tuple(stretch)
            for start in range(0, len(stretch), most_in_a_row):
                yield str(seed), stretch[start:start + most_in_a_row]
