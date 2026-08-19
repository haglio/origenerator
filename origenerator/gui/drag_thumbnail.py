"""The picture that trails the cursor while something is dragged.

Every drag in this app should carry one — a gallery tile onto a combine slot,
the info-pane preview onto the same slot, an enhancement level onto the Enhance
panel — so what is in flight is never in doubt. What each source is showing
lives somewhere different, though: a still sits in a label's pixmap, a looping
WebP in a ``QMovie``, a playing video on the player's own surface with no pixmap
anywhere. Reaching only for ``label.pixmap()`` is how a dragged video came to
trail nothing at all, while a dragged still trailed a picture the size of the
whole preview pane.

So the sources ask here instead, and a drag looks the same wherever it started:
one box, and nothing shown for the one case with genuinely no picture to show.
"""

from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

# Every drag's picture fits this box. Roughly a drop slot's own preview, so what
# is under the cursor reads as the thing that is about to land in the slot —
# and a full-size still from the preview pane no longer swallows the pane it is
# being dragged across.
THUMBNAIL_BOX = 128


def fit_thumbnail(pixmap: QPixmap | None) -> QPixmap:
    """``pixmap`` shrunk into the shared box, or a null pixmap for nothing.

    Only ever shrinks: a source that is already thumbnail-sized (an enhancement
    row's tile) keeps its own pixels rather than being blown up soft.
    """
    if pixmap is None or pixmap.isNull():
        return QPixmap()
    if pixmap.width() <= THUMBNAIL_BOX and pixmap.height() <= THUMBNAIL_BOX:
        return pixmap
    return pixmap.scaled(
        THUMBNAIL_BOX, THUMBNAIL_BOX,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


def label_thumbnail(label) -> QPixmap:
    """The drag picture for whatever a ``QLabel`` is showing.

    A label playing a movie has a null ``pixmap()`` — its picture is the frame
    the movie is on — so a video tile asked the wrong way looks empty.
    """
    movie = label.movie()
    return fit_thumbnail(movie.currentPixmap() if movie is not None else label.pixmap())


def set_drag_thumbnail(drag, pixmap: QPixmap) -> None:
    """Hang ``pixmap`` under the cursor for the length of the gesture.

    A null one is left off rather than set: an empty box following the cursor
    says less than the plain drag cursor does.
    """
    if pixmap is not None and not pixmap.isNull():
        drag.setPixmap(pixmap)
