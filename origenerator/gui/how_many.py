from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSizePolicy

from origenerator.gui.no_wheel import NoWheelComboBox

HOW_MANY = (1, 2, 4, 8, 16, 32)
_HOW_MANY_TIP = "How many to make at once, each with its own seed"


class HowManyPicker(NoWheelComboBox):
    chosen = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("howMany")
        self.setToolTip(_HOW_MANY_TIP)
        for count in HOW_MANY:
            self.addItem(str(count), count)
        self.activated.connect(lambda _index: self.chosen.emit(self.how_many()))

    def how_many(self) -> int:
        return self.currentData()

    def set_how_many(self, count: int) -> None:
        self.setCurrentIndex(HOW_MANY.index(count))


class GenerateWithHowMany(QFrame):
    def __init__(self, generate: QPushButton, how_many: HowManyPicker, parent=None):
        super().__init__(parent)
        self.setObjectName("generateWithHowMany")
        self._how_many = how_many
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(generate)
        how_many.setSizePolicy(how_many.sizePolicy().horizontalPolicy(),
                               QSizePolicy.Policy.Ignored)
        row.addWidget(how_many)

    def offer_how_many(self, offered: bool) -> None:
        self._how_many.setVisible(offered)
