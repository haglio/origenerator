"""Form widgets that stay out of a scrolling form's way.

A QComboBox / QSpinBox / QDoubleSpinBox changes its value on a wheel scroll, so
scrolling a settings form accidentally edits whatever field the cursor happens to
be over. These subclasses ignore the wheel event, so it scrolls the enclosing form
instead of changing the field's value.

The combo also refuses to make its longest item a floor. A model or LoRA picker
holds file names hundreds of pixels wide, and a plain combo cannot be laid out
narrower than the widest of them — so a slim pane grew a horizontal scroll bar
rather than let the field shrink. This one still asks for its full width and gets
it wherever there is room; squeezed, it gives way down to a few characters and
elides what it shows. Only the closed field shrinks: Qt opens the list at its
items' own width, so the names stay whole where they are read — which matters for
two model files that differ only near the end.
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QSizePolicy, QSpinBox, QStyle,
    QStyleOptionComboBox, QStylePainter,
)

# What the combo asks for in place of its longest item: enough to read the head of
# a value, narrow enough that a form full of pickers still fits a slim pane.
_MIN_CONTENTS_CHARS = 8


class NoWheelComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        # A plain combo declares itself unshrinkable (QSizePolicy::Minimum), so a
        # layout takes its preferred width — the longest item — as a floor. This
        # one can shrink, and says so, or the clamp in minimumSizeHint below would
        # never be consulted. What it *prefers* is untouched: a combo laid out at
        # its own hint (the sort picker over the search results) is as wide as it
        # ever was, and only a squeezed one gives width up.
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)

    def wheelEvent(self, event):
        event.ignore()  # let the form scroll; don't change the selection

    def minimumSizeHint(self):
        """_MIN_CONTENTS_CHARS wide, whatever the items or the placeholder say.

        Qt's own minimum is the longest item, and it also widens to hold the
        placeholder text — keeping that width after a choice is made, so a picker
        opening on "Select a workflow…" would prop the pane open at that phrase's
        width for the rest of the session.
        """
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self._floor_width()))
        return hint

    def _floor_width(self) -> int:
        """How wide this combo is holding only _MIN_CONTENTS_CHARS — the same sum
        (frame, arrow, padding, text) Qt makes for a full-length value, so the
        floor tracks the font and the stylesheet rather than guessing at them."""
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        fm = self.fontMetrics()
        text = QSize(fm.horizontalAdvance("X") * _MIN_CONTENTS_CHARS, fm.height())
        return self.style().sizeFromContents(
            QStyle.ContentsType.CT_ComboBox, opt, text, self
        ).width()

    def display_text(self, width: int) -> str:
        """The current value elided to ``width`` — what :meth:`paintEvent` draws.

        Qt clips the label rather than eliding it, so a squeezed picker would cut
        a file name mid-glyph with nothing to say it had been cut.
        """
        return self.fontMetrics().elidedText(
            self.currentText(), Qt.TextElideMode.ElideRight, width
        )

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
        # The style insets the text a pixel each side before drawing it (see
        # QCommonStyle's CE_ComboBoxLabel); elide to what is left after that.
        opt.currentText = self.display_text(max(0, field.width() - 2))
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()
