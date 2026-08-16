"""The stills either side of what a slideshow is showing.

Two small images floated over a fullscreen slideshow — the previous item at the
left edge, the next at the right — so what just passed and what's coming are
visible without stepping to them. They ride *over* the view rather than in its
layout, because the media on screen is already scaled as large as the screen
allows and never gives up a pixel to make room: where the media leaves black
surround beside it (anything but a full-width fit), each still sits centered in
that gutter; where it doesn't, the still sits on top of the media, inset from
the screen edge.
"""

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QRect, QSize

_MARGIN = 12            # gap from the screen edge, and from the media in a gutter
_WIDTH_FRACTION = 0.12  # a still's box, as a share of the view's width…
_HEIGHT_FRACTION = 0.5  # …and of its height
_MIN_WIDTH = 64         # …but never so narrow it says nothing


def still_for(item):
    """What to draw for a neighboring slideshow item, or ``None`` for nothing.

    Its stored thumbnail when the item carries one (a video's only still), else
    the item itself when that's an image — so a slideshow assembled without
    thumbnails still shows its image neighbors.
    """
    if item is None:
        return None
    still = item[3] if len(item) > 3 else None
    if still:
        return still
    return item[0] if item[1] == "image" else None


def side_x(side: str, host_width: int, media_rect: QRect, label_width: int) -> int:
    """Where a neighbor still sits horizontally.

    Centered in the surround beside the media when that gap can hold it clear of
    both edges; otherwise inset from the screen edge and drawn over the media —
    the media is already as large as the screen allows, and shrinking it to make
    room would be the wrong trade.
    """
    if side == "left":
        gutter = max(0, media_rect.x())
        if gutter >= label_width + 2 * _MARGIN:
            return (gutter - label_width) // 2
        return _MARGIN
    media_end = media_rect.x() + media_rect.width()  # QRect.right() is inclusive
    gutter = max(0, host_width - media_end)
    if gutter >= label_width + 2 * _MARGIN:
        return media_end + (gutter - label_width) // 2
    return host_width - label_width - _MARGIN


def _scaled(source, box: QSize):
    """``source`` — a file path or a live frame's encoded bytes — as a pixmap
    scaled into ``box``, never blown up past its own size. ``None`` when there's
    nothing loadable to draw."""
    if source is None:
        return None
    pixmap = QPixmap()
    if isinstance(source, (bytes, bytearray)):
        loaded = pixmap.loadFromData(bytes(source))
    else:
        loaded = pixmap.load(str(source))
    if not loaded or pixmap.isNull():
        return None
    return pixmap.scaled(box.boundedTo(pixmap.size()),
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


class NeighborPreviews:
    """The pair of floating stills, owned by a fullscreen slideshow view."""

    def __init__(self, host: QWidget):
        self._host = host
        self._labels = (self._make_label(host), self._make_label(host))
        self._sources: tuple = (None, None)  # what each side draws (path or bytes)

    @staticmethod
    def _make_label(host: QWidget) -> QLabel:
        label = QLabel(host)
        # The same translucent plate the position caption wears, so a still stays
        # legible where it lands over bright media.
        label.setStyleSheet(
            "background: rgba(0, 0, 0, 140); padding: 4px; border-radius: 4px;"
        )
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Native, because a video surface is a native window on Windows and a
        # plain sibling cannot paint over one however it is stacked — which is
        # why these stills showed beside an image and vanished beside a clip.
        label.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        label.hide()
        return label

    def set_neighbors(self, previous, following, *, media_rect: QRect | None = None):
        """Draw the stills either side of the item on screen. Each is a path, a
        live frame's bytes, or ``None`` for a side with nothing to show."""
        self._sources = (previous, following)
        self.reposition(media_rect)

    def reposition(self, media_rect: QRect | None = None) -> None:
        """Re-scale and re-place both stills for the host's current size, keeping
        clear of ``media_rect`` — where the media is actually drawn — when there's
        room beside it. Without one, the media is taken to fill the view."""
        host = self._host
        if media_rect is None or media_rect.isEmpty():
            media_rect = QRect(0, 0, host.width(), host.height())
        box = QSize(max(_MIN_WIDTH, int(host.width() * _WIDTH_FRACTION)),
                    max(_MIN_WIDTH, int(host.height() * _HEIGHT_FRACTION)))
        for label, source, side in zip(self._labels, self._sources, ("left", "right")):
            pixmap = _scaled(source, box)
            if pixmap is None:
                label.hide()
                continue
            label.setPixmap(pixmap)
            label.adjustSize()
            label.move(side_x(side, host.width(), media_rect, label.width()),
                       max(0, (host.height() - label.height()) // 2))
            label.show()
            label.raise_()  # over the media, under nothing
