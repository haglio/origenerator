"""A small corner badge marking a Recents tile as an image or a video.

The gallery's Recents shelf mixes images and videos in one flow, so each tile
wears a translucent chip in its top-left corner — a play triangle for a video, a
framed photo for an image — to tell them apart at a glance. Elsewhere (inside a
single Images or Videos folder) the type is unambiguous, so no badge is drawn.

Top-left is the one corner of a tile that carries no control: the star, the trash
can and the plus own the other three (see
:mod:`origenerator.gui.corner_controls`), and they keep out of this one — a mark
that only reports has to stay where it has always been, or it moves depending on
which shelf you happened to open.

The badge parents to its tile and positions itself; a tile just constructs one
when it knows its media type. Clicks fall through to the tile beneath it, the way
the tile's own image and caption do.
"""

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt

from origenerator.gui import icons

_INSET = 10  # px from the tile's top-left corner, so the badge sits over the thumbnail


class MediaBadge(QLabel):
    """A play/photo chip overlaid on the top-left corner of a Recents tile."""

    def __init__(self, media_type: str, tile: QWidget):
        super().__init__(tile)
        self.media_type = media_type  # "image"/"video" — which glyph this badge shows
        pixmap = icons.media_type_badge(media_type)
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.move(_INSET, _INSET)
        # Transparent to clicks so selecting/opening the tile still works through it.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()  # above the image label, which is added first
