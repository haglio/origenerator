"""The "3 / 17" plate the fullscreen show floats over the foot of its media.

A show always plays a set — a folder's, a shelf's, or the folder a double-clicked
picture came from — so it always has somewhere in it to be. A suffix carries
whatever else it has to add: the lock.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui.media_overlay import PLATE_CSS, float_over_media

_LOWER_MARGIN = 24  # how far the plate floats above the lower edge


class PositionCaption(QLabel):
    """Where in the set the item on screen is, floated over its lower edge."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setStyleSheet(
            f"color: white; padding: 4px 10px; {PLATE_CSS}"
        )
        float_over_media(self)

    def show_position(self, position: int, total: int, suffix: str = "") -> None:
        """Say the 1-based ``position`` out of ``total``, plus any ``suffix``."""
        self.setText(f"{position} / {total}{suffix}")
        self.reposition()

    def reposition(self) -> None:
        host = self.parentWidget()
        self.adjustSize()
        x = (host.width() - self.width()) // 2
        y = host.height() - self.height() - _LOWER_MARGIN
        self.move(max(0, x), max(0, y))
        self.raise_()  # over the media, video surface included
