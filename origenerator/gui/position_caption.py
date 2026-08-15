"""The "3 / 17" plate a fullscreen view floats over the bottom of its media.

Both fullscreen views page a set, so both say where in it they are, in the same
place and the same plate. A suffix carries whatever else that view has to add —
the slideshow's lock.
"""

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt

_BOTTOM_MARGIN = 24  # how far the plate floats above the bottom edge


class PositionCaption(QLabel):
    """Where in the set the item on screen is, floated over its bottom edge."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 140);"
            " padding: 4px 10px; border-radius: 4px;"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def show_position(self, position: int, total: int, suffix: str = "") -> None:
        """Say the 1-based ``position`` out of ``total``, plus any ``suffix``."""
        self.setText(f"{position} / {total}{suffix}")
        self.reposition()

    def reposition(self) -> None:
        host = self.parentWidget()
        self.adjustSize()
        x = (host.width() - self.width()) // 2
        y = host.height() - self.height() - _BOTTOM_MARGIN
        self.move(max(0, x), max(0, y))
