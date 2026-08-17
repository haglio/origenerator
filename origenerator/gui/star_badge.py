"""A small corner badge marking a thumbnail as a starred image or video.

The user bookmarks individual generations; a starred tile wears a green star in
its top-right corner — opposite the media-type badge and re-roll controls that
sit top-left — so a bookmark reads at a glance. Green is the color Fun Time
marks its favorites in, so one star means one thing across both apps. The badge
parents to its tile and positions itself; the tile shows or hides it as the star
is toggled.

Clicks fall through to the tile beneath it, the way the tile's own image and
caption do.
"""

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt

from origenerator.gui import icons

_INSET = 10  # px from the tile's top-right corner, so the badge sits over the thumbnail


class StarBadge(QLabel):
    """A green-star chip overlaid on the top-right corner of a starred tile."""

    def __init__(self, tile: QWidget):
        super().__init__(tile)
        pixmap = icons.star_badge()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.move(tile.width() - pixmap.width() - _INSET, _INSET)
        # Transparent to clicks so selecting/opening the tile still works through it.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()  # above the image label, which is added first
