from __future__ import annotations

import re

from PyQt6.QtCore import QRegularExpression, QSize, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox

from origenerator.gui.no_wheel import NoWheelDropdown

_PIXELS_EITHER_SIDE_OF_THE_TEXT = 2
_PIXEL_FOR_THE_CURSOR = 1
_WHAT_THE_LINE_EDIT_KEEPS_FOR_ITSELF = 2 * _PIXELS_EITHER_SIDE_OF_THE_TEXT + _PIXEL_FOR_THE_CURSOR


class PresetDropdown(NoWheelDropdown):
    edited = pyqtSignal()

    def __init__(self, presets, unit: str = "", parent=None):
        super().__init__(parent)
        self._unit = unit
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems([self._text_for(preset) for preset in presets])
        unit_pattern = rf"(?:{re.escape(unit)})?\s*" if unit else ""
        self.lineEdit().setValidator(QRegularExpressionValidator(
            QRegularExpression(rf"^\s*\d*\.?\d*\s*{unit_pattern}$"), self))
        # Qt hands a Return the dropdown ignored back to its line edit, so an edit ends twice.
        self._announced = self.currentText()
        self.lineEdit().editingFinished.connect(self._announce_edit)
        self.activated.connect(self._announce_edit)

    def _announce_edit(self, *_):
        text = self.currentText()
        if text != self._announced:
            self._announced = text
            self.edited.emit()

    def _text_for(self, value: float) -> str:
        text = f"{value:g}"
        return f"{text} {self._unit}" if self._unit else text

    def sizeHint(self) -> QSize:
        return self._roomy(super().sizeHint())

    def minimumSizeHint(self) -> QSize:
        return self._roomy(super().minimumSizeHint())

    def _roomy(self, hint: QSize) -> QSize:
        # Qt sizes an editable box to its widest text, with no room for the line edit's own margins.
        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(self.itemText(index))
                      for index in range(self.count())), default=0)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        room = QSize(widest + _WHAT_THE_LINE_EDIT_KEEPS_FOR_ITSELF + metrics.horizontalAdvance("0"),
                     metrics.height())
        hint.setWidth(max(hint.width(), self.style().sizeFromContents(
            QStyle.ContentsType.CT_ComboBox, option, room, self).width()))
        return hint

    def value(self) -> float | None:
        text = self.currentText().strip()
        if self._unit and text.endswith(self._unit):
            text = text[: -len(self._unit)].strip()
        try:
            return float(text)
        except ValueError:
            return None

    def set_value(self, value: float) -> None:
        self.setCurrentText(self._text_for(value))
        self._announced = self.currentText()

    def set_unavailable(self, values, reason: str) -> None:
        unavailable = {self._text_for(value) for value in values}
        for index in range(self.count()):
            if self.itemText(index) in unavailable:
                item = self.model().item(index)
                item.setEnabled(False)
                item.setToolTip(reason)
