"""A small corner badge marking a thumbnail as an enhanced image.

An enhanced generation — one that went through the upscale + low-denoise
re-sample tail, inline or via the standalone enhancer — wears a green plus in
the bottom-right corner of its image area: clear of the media-type badge and
re-roll controls (top-left) and the star (top-right), so all three can coexist.
The badge parents to its tile and positions itself; a tile just constructs one
when its row is enhanced.

Clicks fall through to the tile beneath it, the way the tile's own image and
caption do.
"""

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt

from origenerator.gui import icons

_INSET = 10  # px in from the tile's right edge and up from the image's bottom


class EnhancedBadge(QLabel):
    """A green-plus chip overlaid on the bottom-right of an enhanced tile's
    image area. ``image_bottom`` is the y where that area ends, in tile
    coordinates, so the badge sits over the picture rather than the caption."""

    def __init__(self, tile: QWidget, image_bottom: int):
        super().__init__(tile)
        pixmap = icons.enhance_badge()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.move(tile.width() - pixmap.width() - _INSET,
                  image_bottom - pixmap.height() - _INSET)
        # Transparent to clicks so selecting/opening the tile still works through it.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()  # above the image label, which is added first
