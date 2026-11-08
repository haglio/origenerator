from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget
from shared_ui.spacing import GAP_MEDIUM
from shared_ui.tick_control import TickControl

from origenerator.action_setter_tool import the_setter_tool
from origenerator.action_vocabulary import vocabulary
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import image_actions_row, inherits_image_actions
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.label_cells import LabelCell, LabelForm
from origenerator.gui.pills import PillRow
from origenerator.gui.warning_mark import WarningMark
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.own_window import show_or_say

ACTION_LABEL = "Action"
ACTIONS_LABEL = "Actions"
SIDE_LABELS = {MediaType.IMAGE: "Image Actions", MediaType.VIDEO: "Video Actions"}
ADD = "Add with setter tool…"
EDIT = "Edit with setter tool…"

_TIPS = {MediaType.IMAGE: "Set this image's actions, then every image that has none, one press apiece",
         MediaType.VIDEO: "Set this video's actions, then every video that has none, one press apiece"}


def setter_button(side: str) -> str:
    return f"action.{side}.setter"


def action_pills(side: str) -> str:
    return f"action.{side}.pills"


def adding_button(side: str) -> str:
    return f"action.{side}.add"


def action_checkbox(side: str, name: str) -> str:
    return f"action.{side}.checkbox.{name}"


class _Side(QWidget):
    def __init__(self, side: str, actions: tuple[str, ...], checkboxes: tuple[str, ...], opened,
                 changed):
        super().__init__()
        self._side = side
        self._prompt_id = ""
        self._changed = changed
        self._editable = True
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_MEDIUM)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        column.addLayout(row)
        self._boxes: dict[str, TickControl] = {}
        for name in checkboxes:
            box = TickControl(name)
            box.setObjectName(action_checkbox(side, name))
            box.clicked.connect(lambda _checked=False: self._save())
            self._boxes[name] = box
            row.addWidget(box, 0, Qt.AlignmentFlag.AlignTop)
        self._pills = PillRow(actions, adder_name=adding_button(side))
        self._pills.setObjectName(action_pills(side))
        self._pills.changed.connect(self._pills_changed)
        row.addWidget(self._pills, 1)
        self._setter = QPushButton(ADD, objectName=setter_button(side))
        self._setter.setToolTip(_TIPS[side])
        self._setter.clicked.connect(lambda: opened(side, self._prompt_id))
        column.addWidget(self._setter, 0, Qt.AlignmentFlag.AlignLeft)

    def shows(self, prompt_id: str) -> bool:
        return bool(prompt_id) and prompt_id == self._prompt_id

    def show_actions(self, prompt_id: str, item_actions: ItemActions, *, editable: bool = True) -> None:
        self._prompt_id = prompt_id
        self._editable = editable
        self._setter.setVisible(editable)
        self.set_actions_again(item_actions)

    def set_actions_again(self, item_actions: ItemActions) -> None:
        self._pills.show_names(item_actions.actions, editable=self._editable)
        self._name_the_setter()
        for name, box in self._boxes.items():
            box.setChecked(name in item_actions.checked)

    def _name_the_setter(self) -> None:
        self._setter.setText(EDIT if self._pills.names() else ADD)

    def _pills_changed(self, _names: tuple[str, ...]) -> None:
        self._name_the_setter()
        self._save()

    def _save(self) -> None:
        self._changed(self._prompt_id, self._side, self._item_actions())

    def _item_actions(self) -> ItemActions:
        return ItemActions(self._pills.names(), tuple(name for name, box in self._boxes.items()
                                                 if box.isChecked()))


class ActionRow(QWidget):
    changed = pyqtSignal(str, str, object)

    def __init__(self, form: LabelForm, *, checkboxes: dict[str, tuple[str, ...]] | None = None,
                 actions: dict[str, tuple[str, ...]] | None = None, open_setter=the_setter_tool):
        super().__init__()
        self._open_setter = open_setter
        self._setter_host = None
        self._windows: dict[str, QWidget] = {}
        sides = (MediaType.IMAGE, MediaType.VIDEO)
        if checkboxes is None or actions is None:
            words = {side: vocabulary(side) for side in sides}
            checkboxes = checkboxes if checkboxes is not None else {
                side: words[side].checkboxes for side in sides}
            actions = actions if actions is not None else {
                side: words[side].plain_actions for side in sides}
        self._sides = {side: _Side(side, actions.get(side, ()), checkboxes.get(side, ()), self._open,
                                   self.changed.emit)
                       for side in sides}
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
            image.show_actions(row["prompt_id"], actions_of(row, MediaType.IMAGE))
            image.setEnabled(True)
        else:
            holder = image_actions_row(row, start_image)
            inherited = inherits_image_actions(row, start_image)
            image.show_actions(holder["prompt_id"], actions_of(holder, MediaType.IMAGE),
                              editable=not inherited)
            image.setEnabled(not inherited)
            video.show_actions(row["prompt_id"], actions_of(row, MediaType.VIDEO))
        self._form.setRowVisible(image, True)
        self._form.setRowVisible(video, kind == MediaType.VIDEO)

    def form(self) -> LabelForm:
        return self._form

    def clear(self) -> None:
        for side in self._sides.values():
            self._form.setRowVisible(side, False)

    def set_setter_host(self, host) -> None:
        self._setter_host = host

    def heard(self, prompt_id: str, side: str, item_actions: ItemActions | None) -> None:
        if self._sides[side].shows(prompt_id):
            self._sides[side].set_actions_again(item_actions or ItemActions())

    def _open(self, side: str, prompt_id: str) -> None:
        open_now = self._windows.get(side)
        if open_now is not None and open_now.isVisible():
            open_now.raise_()
            open_now.activateWindow()
            return
        built = self._open_setter(side, prompt_id, heard=self.heard, host=self._setter_host)
        if not show_or_say("Action setter tool", built, parent=self):
            self._windows[side] = built
