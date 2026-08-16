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
        # A video surface is a native window on Windows, and a plain sibling
        # widget cannot paint over one however it is stacked — which is why this
        # plate showed over an image and vanished over a clip. Native itself, it
        # stacks against the video by Z-order like any other window.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)

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
        self.raise_()  # over the media, video surface included
