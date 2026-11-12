from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
)


class NoWheelDropdown(QComboBox):
    floor_chars = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        # QComboBox declares QSizePolicy::Minimum, so a layout takes its longest item as a floor.
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)

    def wheelEvent(self, event):
        event.ignore()

    def minimumSizeHint(self):
        """:attr:`floor_chars` wide, whatever the items or the placeholder say (Qt widens its hints to hold both)."""
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self._floor_width()))
        return hint

    def _floor_width(self) -> int:
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        fm = self.fontMetrics()
        text = QSize(fm.horizontalAdvance("X") * self.floor_chars, fm.height())
        return self.style().sizeFromContents(
            QStyle.ContentsType.CT_ComboBox, opt, text, self
        ).width()

    def display_text(self, width: int) -> str:
        shown = self.currentText() if self.currentIndex() >= 0 else self.placeholderText()
        return self.fontMetrics().elidedText(shown, Qt.TextElideMode.ElideRight, width)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opt,
            QStyle.SubControl.SC_ComboBoxEditField, self,
        )
        # The style insets the text a pixel each side (QCommonStyle, CE_ComboBoxLabel).
        opt.currentText = self.display_text(max(0, field.width() - 2))
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()
