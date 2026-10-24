from __future__ import annotations

import html
from collections.abc import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.folder_path import FolderPath
from shared_ui.icons import marked_text
from shared_ui.spacing import GAP_MEDIUM, GAP_SMALL
from shared_ui.type_scale import SIZE_BODY, in_pixels

from origenerator.gui.copy_button import CopyButton
from origenerator.gui.gallery_tree import PATH_SEPARATOR, PathStep


class FolderPathHeader(QWidget):
    folder_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: tuple[str | None, ...] = ()
        self._path = FolderPath(PATH_SEPARATOR)
        self._path.setWordWrap(True)
        self._path.setStyleSheet(
            f"font-size: {in_pixels(SIZE_BODY)}px; font-weight: bold; padding: {GAP_SMALL}px;")
        self._path.step_clicked.connect(lambda step: self.folder_chosen.emit(self._keys[step]))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        row.addWidget(CopyButton(self.display_text), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._path, 1)

    def show_folder(self, steps: Sequence[PathStep], *, mark: str = "") -> None:
        self._show(steps, links_among=steps[:-1])
        if mark:
            self._lead_the_last_step_with(mark, steps[-1].name)

    def show_search(self, words: str, steps: Sequence[PathStep]) -> None:
        self._show(steps, links_among=steps, lead=words)

    def set_display(self, text: str) -> None:
        self._show([PathStep(text, None)], links_among=())

    def _show(self, steps: Sequence[PathStep], *, links_among: Sequence[PathStep],
              lead: str = "") -> None:
        self._keys = tuple(step.key for step in steps)
        self._path.set_path([step.name for step in steps], lead=lead,
                            linked=[i for i, step in enumerate(links_among) if step.key])

    def _lead_the_last_step_with(self, mark: str, name: str) -> None:
        before, _name, after = self._path.text().rpartition(html.escape(name))
        self._path.setText(before + marked_text(mark, name, color=TEXT_PRIMARY,
                                                size=self._path.fontMetrics().height()) + after)

    def display_text(self) -> str:
        return self._path.plain_text()
