"""Qt sizes a button or a label to its whole text as a floor; these elide to whatever width they are given.

``QFormLayout``'s ``WrapLongRows`` lays a wrapped label out at its own full-line size hint without clamping it to the row, which is why these elide rather than wrap.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QStyleOptionButton,
    QStylePainter,
)
from shared_ui.spacing import MARGIN_STANDARD

_STUB = "XX…"


class ElidingButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._raw = ""
        # A Qt layout takes the stock Minimum policy's full label as a floor; Preferred consults minimumSizeHint.
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)
        self.setText(text)

    def setText(self, text: str):
        """Qt reads a lone "&" as an accelerator marker, so the text carries it doubled; eliding the raw label avoids cutting between the pair."""
        self._raw = text
        super().setText(text.replace("&", "&&"))

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self._floor_width()))
        return hint

    def _floor_width(self) -> int:
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = _STUB
        fm = self.fontMetrics()
        return self.style().sizeFromContents(
            QStyle.ContentsType.CT_PushButton, opt,
            QSize(fm.horizontalAdvance(_STUB), fm.height()), self,
        ).width()

    def display_text(self, width: int) -> str:
        return self.fontMetrics().elidedText(
            self._raw, Qt.TextElideMode.ElideRight, width
        )

    def paintEvent(self, event):
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, self._elided_option())

    def _elided_option(self) -> QStyleOptionButton:
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = self.display_text(self._text_room(opt)).replace("&", "&&")
        return opt

    def _text_room(self, opt: QStyleOptionButton) -> int:
        return self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, self
        ).width()


class ElidingLabel(QLabel):
    def __init__(self, text: str = "", parent=None, *, preferred_width: int = 0):
        super().__init__(text, parent)
        # Qt: asked through the size hint, since a minimum would refuse to give the width back.
        self._preferred_width = preferred_width
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(max(hint.width(), self._preferred_width))
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self.fontMetrics().horizontalAdvance(_STUB)))
        return hint

    def display_text(self, width: int) -> str:
        return self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, width
        )

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOption()
        opt.initFrom(self)
        painter.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt)
        rect = self.contentsRect()
        self.style().drawItemText(
            painter, rect, int(self.alignment()), self.palette(), self.isEnabled(),
            self.display_text(rect.width()), QPalette.ColorRole.WindowText,
        )


def open_the_list_in_full(dropdown) -> None:
    view = dropdown.view()
    advance = dropdown.fontMetrics().horizontalAdvance
    widest = max((advance(dropdown.itemText(i)) for i in range(dropdown.count())), default=0)
    view.setMinimumWidth(widest + view.verticalScrollBar().sizeHint().width()
                         + 2 * view.frameWidth() + 2 * MARGIN_STANDARD)
