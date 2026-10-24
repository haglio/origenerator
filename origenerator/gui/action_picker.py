"""The row on a config tab saying what the item it is showing shows: a picture's,
into the column :mod:`origenerator.sort_pictures` fills in bulk, or a video's act."""
from __future__ import annotations

from funestra.video_families import normalized_text
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

_PICTURES_TIP = "What this picture already shows — which decides what it can be animated as"
_VIDEOS_TIP = "What this video shows — the act it was made as"


def _as_listed(said: str, names: tuple[str, ...]) -> str:
    return next((name for name in names if normalized_text(name) == normalized_text(said)), said)


class ActionPicker(QWidget):
    """What the item on display shows, pickable, for a config tab."""

    chosen = pyqtSignal(str, str)  # prompt_id, what it shows ("" once taken back)

    def __init__(self, states, acts, parent=None):
        super().__init__(parent)
        self._prompt_id = ""
        self._states, self._acts = tuple(states), tuple(acts)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(BUTTON_GAP)
        row.addWidget(ElidingLabel(ACTION_LABEL))
        self._combo = NoWheelComboBox()
        self._offer(self._states)
        self._combo.setToolTip(_PICTURES_TIP)
        self._combo.currentIndexChanged.connect(self._on_picked)
        row.addWidget(self._combo, 1)
        self._sorting = None
        self._sort = QPushButton("Sort pictures…", objectName=SORT_BUTTON)
        self._sort.setToolTip("Say what every picture nobody has answered for shows, "
                              "one press apiece")
        self._sort.clicked.connect(self._on_sort)
        row.addWidget(self._sort)
        self.hide()


    def offered(self) -> list[str]:
        return [self._combo.itemData(i) for i in range(self._combo.count())]

    def picked(self) -> str:
        return self._combo.currentData() or ""

    def pick(self, state: str) -> None:
        self._combo.setCurrentIndex(max(0, self._combo.findData(state)))


    def show_row(self, row: dict) -> None:
        kind = media_type_of_row(row)
        if kind is None:
            self.clear()
            return
        picture = kind == MediaType.IMAGE
        names = self._states if picture else self._acts
        said = _as_listed(row.get("picture_state" if picture else "recipe_category") or "", names)
        self._prompt_id = ""  # nothing is on display while the list is being set
        self._offer(names if picture or not said or said in names else (*names, said))
        self.pick(said)
        self._sort.setVisible(picture)
        self._combo.setToolTip(_PICTURES_TIP if picture else _VIDEOS_TIP)
        self._prompt_id = row.get("prompt_id") or ""
        self.show()

    def _offer(self, names: tuple[str, ...]) -> None:
        self._combo.clear()
        self._combo.addItem(UNSAID, "")
        for name in names:
            self._combo.addItem(name, name)
        open_the_list_in_full(self._combo)

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
        """Someone picked -- silent while an item is being put up, which moves
        the list with nobody having answered."""
        if self._prompt_id:
            self.chosen.emit(self._prompt_id, self.picked())
