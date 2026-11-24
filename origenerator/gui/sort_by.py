from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from shared_ui.spacing import GAP_SMALL

from origenerator.gallery import sort_order
from origenerator.gui.no_wheel import NoWheelDropdown

_LABELS = {
    sort_order.LATEST: "Date (latest first)",
    sort_order.OLDEST: "Date (oldest first)",
    sort_order.LONGEST: "Duration (longest first)",
    sort_order.SHORTEST: "Duration (shortest first)",
}


class SortBy(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chosen = sort_order.LATEST
        self.dropdown = NoWheelDropdown()
        self.dropdown.currentIndexChanged.connect(self._picked)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_SMALL)
        row.addWidget(QLabel("Sort by"))
        row.addWidget(self.dropdown)
        self.hide()

    def chosen(self) -> str:
        return self._chosen

    def choose(self, sort: str | None) -> None:
        self._chosen = sort if sort in _LABELS else sort_order.LATEST

    def for_listing(self, rows: list[dict]) -> str:
        offered = sort_order.offered(rows)
        applied = sort_order.applied(self._chosen, rows)
        self.dropdown.blockSignals(True)
        self.dropdown.clear()
        for sort in offered:
            self.dropdown.addItem(_LABELS[sort], sort)
        self.dropdown.setCurrentIndex(offered.index(applied))
        self.dropdown.blockSignals(False)
        self.show()
        return applied

    def no_listing(self) -> None:
        self.hide()

    def _picked(self, index: int) -> None:
        self._chosen = self.dropdown.itemData(index)
        self.changed.emit()
