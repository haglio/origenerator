"""A small item type icon marking a Latest tile as an image or a video.

The gallery's Latest collection mixes images and videos in one flow, so each tile
wears a translucent ground in its top-left corner — a play triangle for a video, a
framed photo for an image — to tell them apart at a glance. Elsewhere (inside a
single Images or Videos folder) the type is unambiguous, so no item type icon is drawn.

Top-left is the one corner of a tile that carries no control: the star, the trash
can and the plus own the other three (see
:mod:`origenerator.gui.corner_buttons`), and they keep out of this one — a mark
that only reports has to stay where it has always been, or it moves depending on
which collection you happened to open.

The item type icon parents to its tile and positions itself; a tile just constructs one
when it knows its media type. Clicks fall through to the tile beneath it, the way
the tile's own image and caption do.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget
from shared_ui.spacing import MARGIN_STANDARD

from origenerator.gui import icons

_INSET = MARGIN_STANDARD  # px from the tile's top-left corner, so the item type icon sits over the thumbnail


class ItemTypeIcon(QLabel):
    """An item type icon overlaid on the top-left corner of a Latest tile."""

    def __init__(self, media_type: str, tile: QWidget):
        super().__init__(tile)
        self.media_type = media_type  # "image"/"video" — which glyph this item type icon shows
        self._wear(media_type)
        self.move(_INSET, _INSET)
        # Transparent to clicks so selecting/opening the tile still works through it.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.raise_()  # above the image label, which is added first

    def set_media_type(self, media_type: str):
        """Wear another type's glyph.

        For an item type icon over a drop zone whose subject changes kind rather than a tile's,
        which is one thing forever: the Generate tab's source tile shows a video's
        start frame (an image) and the video a cycle was cut out of (a video) in
        the one place, and an item type icon that could not follow said "photo" over both.
        """
        if media_type != self.media_type:
            self.media_type = media_type
            self._wear(media_type)

    def _wear(self, media_type: str):
        pixmap = icons.item_type_icon(media_type)
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
