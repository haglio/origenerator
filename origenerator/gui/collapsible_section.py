"""A titled, collapsible group of form rows.

A header button spans the section; clicking it folds or unfolds the content
below, a ``QFormLayout`` callers fill with ``label: field`` rows. Used by
:class:`~origenerator.gui.param_form.ParamForm` to group a workflow's params
into the sections defined in :mod:`origenerator.gui.param_sections`.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFormLayout,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)
from shared_ui.icons import draw_glyph
from shared_ui.spacing import GAP_MEDIUM, GAP_SMALL, MARGIN_DIALOG

from origenerator.gui.eliding import ElidingButton
from origenerator.gui.warning_mark import WarningMark

# Drawn before the header title so the fold state reads at a glance.
FOLD = {False: "chevron_down", True: "chevron_right"}
_MARK_GAP = GAP_SMALL


class FoldHeader(ElidingButton):
    def __init__(self, *, warns: bool = True):
        super().__init__()
        self._mark: QPixmap | None = None
        self.fold = FOLD[False]
        self.warning = WarningMark(self) if warns else None

    def set_fold(self, fold: str) -> None:
        self.fold = fold
        self.update()

    def set_mark(self, mark: QPixmap | None, tip: str) -> None:
        self._mark = mark
        self.setToolTip(tip)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return self._with_room_for_the_marks(super().sizeHint())

    def minimumSizeHint(self):
        return self._with_room_for_the_marks(super().minimumSizeHint())

    def _with_room_for_the_marks(self, hint: QSize) -> QSize:
        hint.setWidth(hint.width() + self._warning_room() + self._fold_room() + self._mark_room())
        return hint

    def _warning_room(self) -> int:
        return 0 if self.warning is None else self.warning.sizeHint().width() + _MARK_GAP

    def _fold_side(self) -> int:
        return self.fontMetrics().height()

    def _fold_room(self) -> int:
        return self._fold_side() + _MARK_GAP

    def _mark_room(self) -> int:
        return 0 if self._mark is None else _MARK_GAP + self._mark_size().width()

    def _mark_size(self) -> QSize:
        return self._mark.deviceIndependentSize().toSize()

    def _text_room(self, opt: QStyleOptionButton) -> int:
        return (super()._text_room(opt) - self._warning_room() - self._fold_room()
                - self._mark_room())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.warning is None:
            return
        size = self.warning.sizeHint()
        self.warning.setGeometry(QRect(QPoint(0, (self.height() - size.height()) // 2), size))

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = self._elided_option()
        painter.drawControl(QStyle.ControlElement.CE_PushButtonBevel, opt)
        opt.rect = self._title_rect(opt)
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, opt)
        fold = self.fold_rect()
        draw_glyph(painter, self.fold, self.palette().buttonText().color(),
                   size=fold.width(), x=fold.left(), y=fold.top())
        if self._mark is not None:
            painter.drawPixmap(self._mark_rect(), self._mark)

    def _title_rect(self, opt: QStyleOptionButton) -> QRect:
        contents = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, opt, self)
        return contents.adjusted(self._warning_room() + self._fold_room(), 0, 0, 0)

    def fold_rect(self) -> QRect:
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        title_rect = self._title_rect(opt)
        side = self._fold_side()
        return QRect(title_rect.left() - self._fold_room(),
                     title_rect.top() + (title_rect.height() - side) // 2, side, side)

    def _mark_rect(self) -> QRect:
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        title_rect = self._title_rect(opt)
        title = self.display_text(self._text_room(opt))
        size = self._mark_size()
        return QRect(
            QPoint(title_rect.left() + self.fontMetrics().horizontalAdvance(title) + _MARK_GAP,
                   title_rect.top() + (title_rect.height() - size.height()) // 2),
            size)


class CollapsibleSection(QWidget):
    """A header that folds a ``QFormLayout`` of rows open or shut.

    ``toggled`` fires only on a user click of the header, not on a programmatic
    :meth:`set_collapsed`, so a caller restoring a default state can't be mistaken
    for an interaction (the param form repositions its swap button on real toggles).
    """

    toggled = pyqtSignal()

    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        self._collapsed = collapsed

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(GAP_SMALL)

        # Elides its title rather than propping the whole form open at the
        # title's own width; it also handles the "&" in "Models & LoRAs".
        self._header = FoldHeader()
        self._header.setObjectName("foldingSectionHeader")
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle)
        self.warning = self._header.warning
        outer.addWidget(self._header)

        self._content = QWidget()
        self._form = QFormLayout(self._content)
        # Indent the rows under the header, and let the label column size to its
        # widest label with the inputs taking the rest — matching the form's look.
        self._form.setContentsMargins(MARGIN_DIALOG, GAP_SMALL, 0, GAP_SMALL)
        self._form.setSpacing(GAP_MEDIUM)
        self._form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        self._form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        outer.addWidget(self._content)

        self._apply_state()

    # --- state ---------------------------------------------------------------

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool):
        """Fold or unfold without announcing it as a user toggle."""
        self._collapsed = collapsed
        self._apply_state()

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._apply_state()
        self.toggled.emit()

    def _apply_state(self):
        self._content.setVisible(not self._collapsed)
        self._header.set_fold(FOLD[self._collapsed])
        self._header.setText(self._title)

    # --- content -------------------------------------------------------------

    def set_mark(self, mark: QPixmap | None, tip: str) -> None:
        self._header.set_mark(mark, tip)

    def content(self) -> QWidget:
        """The widget holding the rows — the parent for any free-floating child
        (e.g. the swap button) that should fold away with the section."""
        return self._content

    def content_form(self) -> QFormLayout:
        """The layout callers add ``label: field`` rows to."""
        return self._form
