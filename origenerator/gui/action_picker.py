"""The row on a config tab saying what the item it is showing shows: an image's,
into the column :mod:`origenerator.sort_images` fills in bulk, or a video's act."""
from __future__ import annotations

from funestra.video_families import normalized_text
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget
from shared_ui.spacing import GAP_MEDIUM

from origenerator.gallery import media_type_of_row
from origenerator.gui.eliding import ElidingLabel, open_the_list_in_full
from origenerator.gui.label_cells import LabelCell, LabelForm
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.warning_mark import WarningMark
from origenerator.media import MediaType
from origenerator.own_window import show_or_say
from origenerator.sort_images import the_sorting_window

UNSAID = "— "

# What this is called here and on Combine's list of acts.
ACTION_LABEL = "Action"

SORT_BUTTON = "image.sort"

_IMAGES_TIP = "What this image already shows — which decides what it can be animated as"
_VIDEOS_TIP = "What this video shows — the act it was made as"


def _as_listed(said: str, names: tuple[str, ...]) -> str:
    return next((name for name in names if normalized_text(name) == normalized_text(said)), said)


class ActionPicker(QWidget):
    """What the item on display shows, pickable, for a config tab."""

    chosen = pyqtSignal(str, str)  # prompt_id, what it shows ("" once taken back)

    def __init__(self, states, acts, form: LabelForm):
        super().__init__()
        self._prompt_id = ""
        self._states, self._acts = tuple(states), tuple(acts)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        self._combo = NoWheelComboBox()
        self._offer(self._states)
        self._combo.setToolTip(_IMAGES_TIP)
        self._combo.currentIndexChanged.connect(self._on_picked)
        row.addWidget(self._combo, 1)
        self._sorting = None
        self._sort = QPushButton("Set image actions…", objectName=SORT_BUTTON)
        self._sort.setToolTip("Set this image's action, then every image nobody "
                              "has answered for, one press apiece")
        self._sort.clicked.connect(self._on_sort)
        row.addWidget(self._sort)
        self._form = form
        form.addRow(LabelCell(WarningMark(), ElidingLabel(ACTION_LABEL), form.label_column), self)
        form.setRowVisible(self, False)

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
        is_image = kind == MediaType.IMAGE
        names = self._states if is_image else self._acts
        said = _as_listed(row.get("image_state" if is_image else "act") or "", names)
        self._prompt_id = ""  # nothing is on display while the list is being set
        self._offer(names if is_image or not said or said in names else (*names, said))
        self.pick(said)
        self._sort.setVisible(is_image)
        self._combo.setToolTip(_IMAGES_TIP if is_image else _VIDEOS_TIP)
        self._prompt_id = row.get("prompt_id") or ""
        self._form.setRowVisible(self, True)

    def _offer(self, names: tuple[str, ...]) -> None:
        self._combo.clear()
        self._combo.addItem(UNSAID, "")
        for name in names:
            self._combo.addItem(name, name)
        open_the_list_in_full(self._combo)

    def clear(self) -> None:
        self._prompt_id = ""
        self._form.setRowVisible(self, False)

    def _on_sort(self) -> None:
        if self._sorting is not None and self._sorting.isVisible():
            self._sorting.raise_()
            self._sorting.activateWindow()
            return
        built = the_sorting_window(self._prompt_id)
        if not show_or_say("Sorting images", built, parent=self):
            self._sorting = built

    def _on_picked(self) -> None:
        """Someone picked -- silent while an item is being put up, which moves
        the list with nobody having answered."""
        if self._prompt_id:
            self.chosen.emit(self._prompt_id, self.picked())
