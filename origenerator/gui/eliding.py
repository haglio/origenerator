"""Widgets that shorten their text rather than hold a pane open.

Qt sizes a button or a label to its whole text and, squeezed below that, clips it
— so either one sets a floor under everything beside it, and the scroll it sits in
grows a horizontal bar rather than let the column shrink. These ask for a couple of
characters at their narrowest and elide to whatever width they are given: "Show in
Explorer" reads as "Show i…" in a slim pane instead of being cut mid-letter or
dragging a scroll bar in behind it.

Word wrap is the other way to fit a long label into a narrow column, and it is a
trap here: ``QFormLayout``'s ``WrapLongRows`` lays a wrapped label out at its own
full-line size hint without clamping it to the row, so the text runs out past the
pane's right edge — which is worse than either eliding or scrolling, since nothing
on screen says it happened.
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QStyleOptionButton,
    QStylePainter,
)

# What one of these asks for when there is nothing to spare: a letter or two and
# the ellipsis that says the rest was cut.
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


class ElidingLabel(QLabel):
    """A label that elides rather than set the width of the column it sits in.

    Its text stays whole — ``text()`` answers with all of it, and so does the
    tooltip a form puts on it — only what is *drawn* is shortened.
    """

    def __init__(self, text: str = "", parent=None, *, preferred_width: int = 0):
        super().__init__(text, parent)
        # A column of keys lines up by asking for the same width — the widest key
        # in the group — while each label stays free to shrink below it. Asking
        # through the size *hint* rather than a minimum is what allows both: a
        # minimum would line the keys up and then refuse to give the width back.
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
        """The text elided to ``width`` — what :meth:`paintEvent` draws."""
        return self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, width
        )

    def paintEvent(self, event):
        # What QLabel does for a plain-text label, with the text elided on the way
        # in: the background and border the stylesheet asks for, then the text
        # through the style, so it keeps the color and the alignment it would have.
        painter = QStylePainter(self)
        opt = QStyleOption()
        opt.initFrom(self)
        painter.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt)
        rect = self.contentsRect()
        self.style().drawItemText(
            painter, rect, int(self.alignment()), self.palette(), self.isEnabled(),
            self.display_text(rect.width()), QPalette.ColorRole.WindowText,
        )
