"""A small copy-to-clipboard icon button, shared wherever a value is worth
lifting to the clipboard in one click — a metadata filename, a prompt, a seed.

The value can be fixed (a string) or live (a zero-arg callable read at click
time), so the same button serves a read-only label and an editable form field.
"""

from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import CANVAS, glyph_pixmap


class CopyButton(QPushButton):
    """Copies ``source`` to the clipboard. ``source`` is the text itself, or a
    zero-arg callable returning it — read at click time so an editable field's
    current value is copied, not whatever it held when the button was built."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.setObjectName("copyButton")
        self.setIcon(_copy_icon())
        self.setIconSize(QSize(14, 14))
        self.setToolTip("Copy to clipboard")
        self.setStyleSheet("padding: 2px 6px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
