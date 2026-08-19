"""A push button that shortens its label rather than hold a pane open.

Qt sizes a button to its whole label and, squeezed below that, clips it — so a
button anywhere in a form sets a floor under everything beside it, and the scroll
it sits in grows a horizontal bar instead of letting the column shrink. This one
asks for a couple of characters at its narrowest and elides its label to whatever
width it is given: "Show in Explorer" reads as "Show i…" in a slim pane instead of
being cut mid-letter or dragging a scroll bar in behind it.
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QPushButton, QSizePolicy, QStyle, QStyleOptionButton, QStylePainter,
)

# What the button asks for when there is nothing to spare: a letter or two and the
# ellipsis that says the rest was cut.
_STUB = "XX…"


class ElidingButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._raw = ""
        # Preferred, not the stock Minimum: a layout reads Minimum as "this may
        # grow but never shrink" and takes the full label as a floor, which is the
        # whole problem. Preferred consults minimumSizeHint below instead.
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)
        self.setText(text)

    def setText(self, text: str):
        """Set the label, keeping the unescaped copy the eliding paint needs.

        Qt reads a lone "&" as an accelerator marker, so a button's text carries
        it doubled ("Model && LoRA"); eliding that string could cut between the
        pair and leave the survivor swallowing the next character. Eliding the raw
        label and doubling afterwards can't. ``text()`` still answers with the
        doubled form, as any other button's does.
        """
        self._raw = text
        super().setText(text.replace("&", "&&"))

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self._floor_width()))
        return hint

    def _floor_width(self) -> int:
        """How wide this button is holding only the stub — the same sum (border,
        padding, whatever the stylesheet adds) the style makes for a full label,
        so the floor tracks the font and the theme rather than guessing at them."""
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = _STUB
        fm = self.fontMetrics()
        return self.style().sizeFromContents(
            QStyle.ContentsType.CT_PushButton, opt,
            QSize(fm.horizontalAdvance(_STUB), fm.height()), self,
        ).width()

    def display_text(self, width: int) -> str:
        """The label elided to ``width`` — what :meth:`paintEvent` draws."""
        return self.fontMetrics().elidedText(
            self._raw, Qt.TextElideMode.ElideRight, width
        )

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        room = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, self
        ).width()
        opt.text = self.display_text(room).replace("&", "&&")
        painter.drawControl(QStyle.ControlElement.CE_PushButton, opt)
