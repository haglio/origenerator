"""A small copy-to-clipboard icon button, shared wherever a value is worth
lifting to the clipboard in one click — a metadata filename, a prompt, a seed —
and the shape it lends a button set beside it, so the two read as a pair.

The value can be fixed (a string) or live (a zero-arg callable read at click
time), so the same button serves a read-only label and an editable form field.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QPushButton
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import CANVAS, glyph_pixmap
from shared_ui.spacing import BUTTON_MARK_INSET, BUTTON_PAD_H_TIGHT


class IconButton(QPushButton):
    """A small button wearing only its mark: the copy button's shape."""

    def __init__(self, icon: QIcon, tooltip: str, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setIcon(icon)
        self.setIconSize(QSize(14, 14))
        self.setToolTip(tooltip)
        self.setStyleSheet(f"padding: {BUTTON_MARK_INSET}px {BUTTON_PAD_H_TIGHT}px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class CopyButton(IconButton):
    """Copies ``source`` to the clipboard. ``source`` is the text itself, or a
    zero-arg callable returning it — read at click time so an editable field's
    current value is copied, not whatever it held when the button was built."""

    def __init__(self, source, parent=None):
        super().__init__(_copy_icon(), "Copy to clipboard", "copyButton", parent)
        self._source = source
        self.clicked.connect(self._copy)

    def _copy(self):
        text = self._source() if callable(self._source) else self._source
        QApplication.clipboard().setText(text)


def _copy_icon() -> QIcon:
    """The familiar two-overlapping-sheets copy glyph.

    The family's drawing, out of :mod:`shared_ui.icons` -- Fun Time's log-panel
    copy button wears the same one.  Each app drew its own before, at its own
    proportions, and the two apps sit on screen together.
    """
    return QIcon(glyph_pixmap("copy", int(CANVAS), TEXT_SECONDARY))
