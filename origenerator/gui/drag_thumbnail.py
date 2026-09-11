"""Dragging something out of a widget: the gesture, and the picture it trails.

The gesture is the same wherever it starts — note where the left button went
down, and only once the pointer has travelled the platform's own drag distance
does the press stop being a click and become a drag. Three widgets wrote that
out by hand under three different field names, which is three chances to get the
threshold wrong and one reason a plain click somewhere could start a drag.
:class:`DragOut` is it once; each caller keeps only what it carries, what it
shows, and its own reason to refuse.

Every drag in this app should carry one — a gallery tile onto a combine slot,
the info-pane preview onto the same slot, an enhancement level onto the Enhance
panel — so what is in flight is never in doubt. What each source is showing
lives somewhere different, though: a still sits in a label's pixmap, a looping
WebP in a ``QMovie``, a playing video on the player's own surface with no pixmap
anywhere. Reaching only for ``label.pixmap()`` is how a dragged video came to
trail nothing at all, while a dragged still trailed a picture the size of the
whole preview pane.

So the sources ask here instead, and a drag looks the same wherever it started:
one size, and nothing shown for the one case with genuinely no picture to show.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import QApplication

# Every drag's picture fits inside this. Roughly a drop slot's own preview, so what
# is under the cursor reads as the thing that is about to land in the slot —
# and a full-size still from the preview pane no longer swallows the pane it is
# being dragged across.
THUMBNAIL_MAX = 128


def fit_thumbnail(pixmap: QPixmap | None) -> QPixmap:
    """``pixmap`` shrunk into the shared size, or a null pixmap for nothing.

    Only ever shrinks: a source that is already thumbnail-sized (an enhancement
    row's tile) keeps its own pixels rather than being blown up soft.
    """
    if pixmap is None or pixmap.isNull():
        return QPixmap()
    if pixmap.width() <= THUMBNAIL_MAX and pixmap.height() <= THUMBNAIL_MAX:
        return pixmap
    return pixmap.scaled(
        THUMBNAIL_MAX, THUMBNAIL_MAX,
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

    A null one is left off rather than set: an empty square following the cursor
    says less than the plain drag cursor does.
    """
    if pixmap is not None and not pixmap.isNull():
        drag.setPixmap(pixmap)


class DragOut:
    """One widget's press-then-threshold drag gesture.

    Held by the widget that can be dragged out of; fed its presses and moves.
    A caller with its own reason to refuse (nothing armed to drag, a version
    with no settings to take) checks that before asking, so the press is still
    waiting if the reason goes away.
    """

    def __init__(self):
        self._origin: QPoint | None = None

    @property
    def pressed(self) -> bool:
        """Whether a press is still waiting to become a click or a drag."""
        return self._origin is not None

    def forget(self) -> None:
        """Drop the pending press — the gesture turned out to be something else."""
        self._origin = None

    def note_press(self, event) -> None:
        """Remember where a left press landed, as a possible drag's origin."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()

    def should_start(self, event) -> bool:
        """Whether this move has carried the press far enough to be a drag.

        Forgets the origin once it has, so one press starts one drag; a plain
        click, having never got this far, still reaches the click handlers.
        """
        if self._origin is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return False
        moved = (event.position().toPoint() - self._origin).manhattanLength()
        if moved < QApplication.startDragDistance():
            return False
        self._origin = None
        return True

    @staticmethod
    def start(widget, mime, pixmap: QPixmap, *, on_started=None, on_ended=None) -> None:
        """Carry *mime* out of *widget*, with *pixmap* trailing the cursor.

        ``on_started`` and ``on_ended`` bracket the whole gesture rather than the
        call: ``QDrag.exec`` is modal, so a drop slot lit by the first stays lit
        until the drop, and the second runs even when the drag is abandoned.
        """
        drag = QDrag(widget)
        drag.setMimeData(mime)
        set_drag_thumbnail(drag, pixmap)
        if on_started is not None:
            on_started()
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            if on_ended is not None:
                on_ended()
