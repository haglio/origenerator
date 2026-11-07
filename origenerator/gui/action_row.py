from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from shared_ui.spacing import GAP_MEDIUM
from shared_ui.tick_control import TickControl

from origenerator.action_labels import Labels, labels_of
from origenerator.action_setter_tool import the_setter_tool
from origenerator.action_vocabulary import vocabulary
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import image_labels_row, inherits_image_labels
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.label_cells import LabelCell, LabelForm
from origenerator.gui.warning_mark import WarningMark
from origenerator.media import MediaType
from origenerator.own_window import show_or_say

ACTION_LABEL = "Action"
ACTIONS_LABEL = "Actions"
SIDE_LABELS = {MediaType.IMAGE: "Image Actions", MediaType.VIDEO: "Video Actions"}
UNSAID = "—"
ADD = "Add actions with setter tool…"
EDIT = "Edit actions with setter tool…"

_TIPS = {MediaType.IMAGE: "Set this image's actions, then every image that has none, one press apiece",
         MediaType.VIDEO: "Set this video's actions, then every video that has none, one press apiece"}


def setter_button(side: str) -> str:
    return f"action.{side}.setter"


def listed_actions(side: str) -> str:
    return f"action.{side}.listed"


def action_checkbox(side: str, name: str) -> str:
    return f"action.{side}.checkbox.{name}"


class _Side(QWidget):
    def __init__(self, side: str, checkboxes: tuple[str, ...], opened, changed):
        super().__init__()
        self._side = side
        self._prompt_id = ""
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_MEDIUM)
        self._listed = QLabel(UNSAID)
        self._listed.setWordWrap(True)
        self._listed.setObjectName(listed_actions(side))
        column.addWidget(self._listed)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        column.addLayout(row)
        self._setter = QPushButton(ADD, objectName=setter_button(side))
        self._setter.setToolTip(_TIPS[side])
        self._setter.clicked.connect(lambda: opened(side, self._prompt_id))
        row.addWidget(self._setter)
        self._boxes: dict[str, TickControl] = {}
        for name in checkboxes:
            box = TickControl(name)
            box.setObjectName(action_checkbox(side, name))
            box.clicked.connect(lambda _checked=False: changed(self._prompt_id, side, self._labels()))
            self._boxes[name] = box
            row.addWidget(box)
        row.addStretch(1)
        self._actions: tuple[str, ...] = ()

    def shows(self, prompt_id: str) -> bool:
        return bool(prompt_id) and prompt_id == self._prompt_id

    def show_labels(self, prompt_id: str, labels: Labels) -> None:
        self._prompt_id = prompt_id
        self.relabel(labels)

    def relabel(self, labels: Labels) -> None:
        self._actions = labels.actions
        said = ", ".join(labels.actions)
        self._listed.setText(said or UNSAID)
        self._setter.setText(EDIT if labels.actions else ADD)
        for name, box in self._boxes.items():
            box.setChecked(name in labels.checked)

    def _labels(self) -> Labels:
        return Labels(self._actions, tuple(name for name, box in self._boxes.items()
                                           if box.isChecked()))


class ActionRow(QWidget):
    changed = pyqtSignal(str, str, object)

    def __init__(self, form: LabelForm, *, checkboxes: dict[str, tuple[str, ...]] | None = None,
                 open_setter=the_setter_tool):
        super().__init__()
        self._open_setter = open_setter
        self._windows: dict[str, QWidget] = {}
        boxes = checkboxes if checkboxes is not None else {
            side: vocabulary(side).checkboxes for side in (MediaType.IMAGE, MediaType.VIDEO)}
        self._sides = {side: _Side(side, boxes.get(side, ()), self._open, self.changed.emit)
                       for side in (MediaType.IMAGE, MediaType.VIDEO)}
        self._names = {side: ElidingLabel(SIDE_LABELS[side]) for side in self._sides}
        self._form = form
        for side, shown in self._sides.items():
            form.addRow(LabelCell(WarningMark(), self._names[side], form.label_column), shown)
            form.setRowVisible(shown, False)

    def show_row(self, row: dict, start_image: dict | None = None) -> None:
        kind = media_type_of_row(row)
        if kind is None:
            self.clear()
            return
        image, video = self._sides[MediaType.IMAGE], self._sides[MediaType.VIDEO]
        self._names[MediaType.IMAGE].setText(
            ACTIONS_LABEL if kind == MediaType.IMAGE else SIDE_LABELS[MediaType.IMAGE])
        if kind == MediaType.IMAGE:
            image.show_labels(row["prompt_id"], labels_of(row, MediaType.IMAGE))
            image.setEnabled(True)
        else:
            holder = image_labels_row(row, start_image)
            inherited = inherits_image_labels(row, start_image)
            image.show_labels(holder["prompt_id"], labels_of(holder, MediaType.IMAGE))
            image.setEnabled(not inherited)
            video.show_labels(row["prompt_id"], labels_of(row, MediaType.VIDEO))
        self._form.setRowVisible(image, True)
        self._form.setRowVisible(video, kind == MediaType.VIDEO)

    def form(self) -> LabelForm:
        return self._form

    def clear(self) -> None:
        for side in self._sides.values():
            self._form.setRowVisible(side, False)

    def heard(self, prompt_id: str, side: str, labels: Labels | None) -> None:
        if self._sides[side].shows(prompt_id):
            self._sides[side].relabel(labels or Labels())

    def _open(self, side: str, prompt_id: str) -> None:
        open_now = self._windows.get(side)
        if open_now is not None and open_now.isVisible():
            open_now.raise_()
            open_now.activateWindow()
            return
        built = self._open_setter(side, prompt_id, heard=self.heard)
        if not show_or_say("Action setter tool", built, parent=self):
            self._windows[side] = built
