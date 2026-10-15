"""The row on a config tab saying what the picture it is showing shows: the one
on screen, into the column :mod:`origenerator.sort_pictures` fills in bulk."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget
from shared_ui.spacing import BUTTON_GAP

from origenerator.gallery import media_type_of_row
from origenerator.gui.eliding import ElidingLabel, open_the_list_in_full
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.media import MediaType
from origenerator.own_window import show_or_say
from origenerator.sort_pictures import the_sorting_window

UNSAID = "— "

# What this is called here and on Combine's list of acts.
ACTION_LABEL = "Action"

SORT_BUTTON = "picture.sort"


class PictureStatePicker(QWidget):
    """What the picture on display shows, pickable, for a config tab."""

    chosen = pyqtSignal(str, str)  # prompt_id, state ("" once an answer is taken back)

    def __init__(self, states, parent=None):
        super().__init__(parent)
        self._prompt_id = ""
        self._states = tuple(states)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(BUTTON_GAP)
        row.addWidget(ElidingLabel(ACTION_LABEL))
        self._states_combo = NoWheelComboBox()
        self._states_combo.addItem(UNSAID, "")
        for state in self._states:
            self._states_combo.addItem(state, state)
        open_the_list_in_full(self._states_combo)
        self._states_combo.setToolTip(
            "What this picture already shows — which decides what it can be "
            "animated as")
        self._states_combo.currentIndexChanged.connect(self._on_picked)
        row.addWidget(self._states_combo, 1)
        self._sorting = None
        sort = QPushButton("Sort pictures…", objectName=SORT_BUTTON)
        sort.setToolTip("Say what every picture nobody has answered for shows, "
                        "one press apiece")
        sort.clicked.connect(self._on_sort)
        row.addWidget(sort)
        self.hide()


    def offered(self) -> list[str]:
        return [self._states_combo.itemData(i) for i in range(self._states_combo.count())]

    def chosen_state(self) -> str:
        return self._states_combo.currentData() or ""

    def pick(self, state: str) -> None:
        self._states_combo.setCurrentIndex(max(0, self.offered().index(state)))


    def show_row(self, row: dict) -> None:
        if media_type_of_row(row) != MediaType.IMAGE:
            self.clear()
            return
        self._prompt_id = ""  # no picture is on display while the list is being set
        self.pick(row.get("picture_state") or "")
        self._prompt_id = row.get("prompt_id") or ""
        self.show()

    def clear(self) -> None:
        self._prompt_id = ""
        self.hide()

    def _on_sort(self) -> None:
        if self._sorting is not None and self._sorting.isVisible():
            self._sorting.raise_()
            self._sorting.activateWindow()
            return
        built = the_sorting_window()
        if not show_or_say("Sorting pictures", built, parent=self):
            self._sorting = built

    def _on_picked(self) -> None:
        """Someone picked -- silent while a picture is being put up, which moves
        the list with nobody having answered."""
        if self._prompt_id:
            self.chosen.emit(self._prompt_id, self.chosen_state())
