"""An editable picker of common numeric values that still takes any typed one."""

import re

from PyQt6.QtCore import QRegularExpression, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QComboBox

from origenerator.gui.no_wheel import NoWheelComboBox


class PresetComboBox(NoWheelComboBox):
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
        # Return in an editable combo reaches the line edit twice (the combo
        # hands the key it ignored back to it), so each end of an edit is
        # announced once, by its text.
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
        """Grey out these presets so they can't be picked, and say why on hover.

        A preset the model can't produce is worse than a missing one: chosen, it
        silently becomes a different setting, and the number the user picked is
        not the number they get. Greyed rather than dropped so the list still
        reads as the same list at every workflow, with the ones out of reach
        visibly out of reach.
        """
        unavailable = {self._text_for(value) for value in values}
        for index in range(self.count()):
            if self.itemText(index) in unavailable:
                item = self.model().item(index)
                item.setEnabled(False)
                item.setToolTip(reason)
