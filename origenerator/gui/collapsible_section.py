"""A titled, collapsible group of form rows.

A header button spans the section; clicking it folds or unfolds the content
below, a ``QFormLayout`` callers fill with ``label: field`` rows. Used by
:class:`~origenerator.gui.param_form.ParamForm` to group a workflow's params
into the sections defined in :mod:`origenerator.gui.param_sections`.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

# Prefixed to the header title so the fold state reads at a glance: a down
# triangle when open, a right-pointing one when shut.
_ARROW_OPEN = "▾"   # ▾
_ARROW_SHUT = "▸"   # ▸


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
        outer.setSpacing(2)

        self._header = QPushButton()
        self._header.setObjectName("sectionHeader")
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle)
        outer.addWidget(self._header)

        self._content = QWidget()
        self._form = QFormLayout(self._content)
        # Indent the rows under the header, and let the label column size to its
        # widest label with the inputs taking the rest — matching the form's look.
        self._form.setContentsMargins(12, 2, 0, 4)
        self._form.setSpacing(6)
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
        arrow = _ARROW_SHUT if self._collapsed else _ARROW_OPEN
        # Double any "&" so QPushButton renders it literally ("Model & LoRA")
        # instead of swallowing it as a keyboard-accelerator marker.
        title = self._title.replace("&", "&&")
        self._header.setText(f"{arrow}  {title}")

    # --- content -------------------------------------------------------------

    def content(self) -> QWidget:
        """The widget holding the rows — the parent for any free-floating child
        (e.g. the swap button) that should fold away with the section."""
        return self._content

    def content_form(self) -> QFormLayout:
        """The layout callers add ``label: field`` rows to."""
        return self._form
