from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from origenerator import gallery
from origenerator.action_setter_tool import the_setter_tool
from origenerator.gallery.source_image import start_images_among
from origenerator.gui.action_row import ActionRow
from origenerator.gui.label_cells import LabelForm
from origenerator.published_actions import set_many_actions


class FolderActions(QWidget):
    saved = Signal(str, object)

    def __init__(self, db, image_rows: Callable[[], list[dict]], *, checkboxes=None, actions=None,
                 open_setter=the_setter_tool, parent=None):
        super().__init__(parent)
        self._db = db
        self._image_rows = image_rows
        form = LabelForm(self)
        form.setContentsMargins(0, 0, 0, 0)
        self._row = ActionRow(form, checkboxes=checkboxes, actions=actions, open_setter=open_setter)
        self._row.changed.connect(self._save)
        self._row.told.connect(self.saved)
        self.hide()

    def show_folder(self, group) -> None:
        rows = self._finished_items_of(group)
        if not rows:
            self.hide()
            return
        start_of = start_images_among(self._image_rows())
        self._row.show_folder(rows, {row["prompt_id"]: self._db.get_generation(start["prompt_id"])
                                     for row in rows if (start := start_of(row)) is not None})
        self.show()

    def _finished_items_of(self, group) -> list[dict]:
        if not isinstance(group, gallery.SettingsGroup):
            return []
        return [row for listed in group.rows
                if (row := self._db.get_generation(listed["prompt_id"])) is not None
                and gallery.produced_output(row)]

    def hear(self, side: str, actions_by_id: dict) -> None:
        self._row.hear(side, actions_by_id)

    def set_setter_host(self, host) -> None:
        self._row.set_setter_host(host)

    def _save(self, side: str, actions_by_id: dict) -> None:
        self.saved.emit(side, set_many_actions(self._db, side, actions_by_id).after)
