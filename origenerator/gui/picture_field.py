"""A setting that holds a picture to start from, drawn in the well Combine's slots
wear and named the way the gallery names it, never by its file."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from origenerator.gui import grid_card
from origenerator.gui.drop_slot import _PREVIEW_SIZE, DropWell
from origenerator.workflows.derived_size import resolve_input_image_path

PictureNamer = Callable[[str], tuple[str | None, str]]
_EMPTY = "Drop an image"


def its_own_file(value: str) -> tuple[str | None, str]:
    path = resolve_input_image_path(value)
    if path is None or not path.is_file():
        return None, ""
    return str(path), path.name


class PictureField(QWidget):
    textChanged = pyqtSignal(str)

    def __init__(self, name_picture: PictureNamer = its_own_file, parent=None):
        super().__init__(parent)
        self._name_picture = name_picture
        self._value = ""
        self._well = DropWell(_EMPTY)
        self._well.ensurePolished()
        edge = self._well.contentsMargins()
        self._well.setFixedSize(_PREVIEW_SIZE + edge.left() + edge.right(),
                                _PREVIEW_SIZE + edge.top() + edge.bottom())
        self._name = QLabel()
        self._name.setWordWrap(True)
        grid_card.style_caption(self._name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._well)
        layout.addWidget(self._name)

    def text(self) -> str:
        return self._value

    def setText(self, value: str) -> None:
        if value == self._value:
            return
        self._value = value
        picture, name = self._name_picture(value) if value else (None, "")
        if not self._well.show_picture(picture):
            self._well.setPixmap(QPixmap())
            self._well.setText("✓" if value else _EMPTY)
        self._name.setText(name)
        self.textChanged.emit(value)

    def set_candidate(self, active: bool) -> None:
        self._well.set_candidate(active)
