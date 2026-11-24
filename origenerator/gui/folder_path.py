from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QWidget
from shared_ui import folder_path as shared_folder_path
from shared_ui.spacing import GAP_MEDIUM, GAP_SMALL
from shared_ui.type_scale import SIZE_BODY, in_pixels

from origenerator.gui.copy_button import CopyButton
from origenerator.gui.gallery_tree import PATH_SEPARATOR, PathStep
from origenerator.gui.widget_size import narrowest_on_fewest_rows


class FolderPath(QWidget):
    folder_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: tuple[str | None, ...] = ()
        self._one_line_width: int | None = None
        self._path = shared_folder_path.FolderPath(PATH_SEPARATOR)
        self._path.setWordWrap(True)
        self._path.setStyleSheet(
            f"font-size: {in_pixels(SIZE_BODY)}px; font-weight: bold; padding: {GAP_SMALL}px;")
        self._path.step_clicked.connect(lambda step: self.folder_chosen.emit(self._keys[step]))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        row.addWidget(CopyButton(self.display_text), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._path, 1)

    def show_folder(self, steps: Sequence[PathStep], *,
                    mark: tuple[str, QColor] | None = None) -> None:
        self._show(steps, links_among=steps[:-1], icons={len(steps) - 1: mark} if mark else None)

    def show_search(self, words: str, steps: Sequence[PathStep]) -> None:
        self._show(steps, links_among=steps, lead=words)

    def set_display(self, text: str) -> None:
        self._show([PathStep(text, None)], links_among=())

    def _show(self, steps: Sequence[PathStep], *, links_among: Sequence[PathStep],
              lead: str = "", icons: Mapping[int, tuple[str, QColor]] | None = None) -> None:
        self._keys = tuple(step.key for step in steps)
        self._one_line_width = None
        self._path.set_path([step.name for step in steps], lead=lead, icons=icons,
                            linked=[i for i, step in enumerate(links_among) if step.key])

    def sizeHint(self) -> QSize:
        if self._one_line_width is None:
            self._one_line_width = narrowest_on_fewest_rows(self)
        return QSize(self._one_line_width, self.heightForWidth(self._one_line_width))

    def display_text(self) -> str:
        return self._path.plain_text()
