"""An editable picker of common numeric values that still takes any typed one."""
from __future__ import annotations

import re

from PyQt6.QtCore import QRegularExpression, QSize, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox

from origenerator.gui.no_wheel import NoWheelComboBox

# What the line edit inside the box keeps for itself: a couple of pixels either
# side of the text, and one more for the cursor at its end.
_FIELD_MARGINS = 5


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

    def sizeHint(self) -> QSize:
        return self._roomy(super().sizeHint())

    def minimumSizeHint(self) -> QSize:
        return self._roomy(super().minimumSizeHint())

    def _roomy(self, hint: QSize) -> QSize:
        """``hint``, never narrower than the longest preset needs to read whole.

        Qt sizes an editable box to the widest text it lists and stops there,
        with nothing left for the margins the line edit keeps around what it
        shows. A few pixels short, that field scrolls its text rather than
        clipping it -- so the preset picked wasn't cut off, it was a different
        number: "10 s" read as "0 s", a length nothing here offers. Ask for the
        text, the margins, and a digit more so a typed value has somewhere to go.
        """
        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(self.itemText(index))
                      for index in range(self.count())), default=0)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        room = QSize(widest + _FIELD_MARGINS + metrics.horizontalAdvance("0"),
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
