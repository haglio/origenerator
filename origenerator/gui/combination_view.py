"""The two halves of a combination, shown as the sum they are: image + recipe.

Two renderings of one look. :class:`CombinationView` is the live one, for a pane
with room to loop the clip; :func:`combination_pixmap` is the same arithmetic as
a still, for the surfaces that hold a picture rather than a widget — the queue
strip's corner and a folder's re-roll tile. They are together here because what
they have to agree on is the look: a run in flight shows the same pair in all
three places until ComfyUI streams a frame of the run itself, and three
surfaces each drawing their own idea of it is what left one blurred, one blank
and one missing its plus.

What "Edit…" hands a tab is not a generation — it is a picture and a
past video's settings, and nothing has been made from them yet. The form below
holds the settings, but the pane above it had nothing to show and said so, with
the same "select a generation to preview" a tab that had been pointed at nothing
says. So it shows the arithmetic instead: the frame that will be animated on the
left, a plus sign, and on the right the clip whose settings the run will follow,
looping in gray (:mod:`origenerator.gui.grayscale`) because it is the recipe and
not the result.

Both pictures are square-fit into whatever height the pane has, side by side, so
the pair reads as one line of arithmetic at any size the pane is dragged to.
"""

from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QMovie, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from origenerator.gui.grayscale import play_grayscale
from origenerator.gui.looping_preview import fit_size, looping_movie
from origenerator.gui.queue_thumbs import fitted_cell
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import TEXT_MUTED

# How much of the pane's height a picture takes, leaving room for the plus sign
# to breathe between them and the pane's own margins around them.
_HEIGHT_SHARE = 0.8
# The plus, as a fraction of a picture's side — big enough to read as the operator
# joining them rather than as a mark on one of the pictures.
_PLUS_SHARE = 0.28
_MIN_PLUS_PT = 12


def combination_pixmap(image_path, video_path, size: QSize) -> QPixmap | None:
    """The pair as one still picture, fitted into ``size`` — or ``None`` for a
    run made from nothing, which is a plate the caller leaves alone.

    The same arithmetic :class:`CombinationView` lays out live: the frame, the
    plus, and the clip whose settings go with it, drained of color because it is
    not what is being made. Either half alone still draws, and the plus shows
    only with both, since a lone picture is not a sum.

    A still rather than the widget because the surfaces that want it are a
    thumbnail-sized label apiece, redrawn on every poll — and the halves come
    from :func:`~origenerator.gui.queue_thumbs.fitted_cell`, so a picture the
    strip has already scaled this second is not scaled again for the tile.
    """
    side = _pair_side(size, bool(image_path and video_path))
    image = fitted_cell(image_path, side)
    recipe = fitted_cell(video_path, side, gray=True)
    parts = [part for part in (image, recipe) if part is not None]
    if not parts:
        return None
    plus = _plus_width(side) if len(parts) == 2 else 0
    width = len(parts) * side + plus
    canvas = QPixmap(width, side)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, parts[0])
    if len(parts) == 2:
        painter.setPen(QColor(TEXT_MUTED))
        font = painter.font()
        font.setPointSize(max(_MIN_PLUS_PT, int(side * _PLUS_SHARE)))
        painter.setFont(font)
        painter.drawText(QRect(side, 0, plus, side),
                         Qt.AlignmentFlag.AlignCenter, "+")
        painter.drawPixmap(side + plus, 0, parts[1])
    painter.end()
    return canvas


def _pair_side(size: QSize, both: bool) -> int:
    """The square each half is fitted into, so the sum fits ``size`` across."""
    if not both:
        return max(1, min(size.width(), size.height()))
    room = size.width() / (2 + _PLUS_SHARE)   # two squares and the operator
    return max(1, int(min(room, size.height())))


def _plus_width(side: int) -> int:
    """The gap the operator sits in, in proportion to the squares beside it."""
    return max(_MIN_PLUS_PT, int(side * _PLUS_SHARE))


def _readable(path) -> QPixmap | None:
    """The picture at ``path``, or ``None`` when there is none to load — a frame
    the library has since moved is an ordinary case, not an error."""
    if not path or not Path(path).is_file():
        return None
    picture = QPixmap(str(path))
    return None if picture.isNull() else picture


class CombinationView(QWidget):
    """An image, a plus, and the gray clip whose settings go with it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_path: str | None = None
        self._video_path: str | None = None
        self._movie: QMovie | None = None
        self._pixmap: QPixmap | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        layout.addStretch(1)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)
        self.plus_label = QLabel("+")
        self.plus_label.setObjectName("estimateLabel")  # muted, like the pane's own text
        self.plus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.plus_label)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.video_label)
        layout.addStretch(1)
        # Clicks fall through to the pane, which owns the double-click that opens
        # a show — there is nothing here to open, so nothing here should eat one.
        for label in (self.image_label, self.plus_label, self.video_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def show_pair(self, image_path, video_path) -> None:
        """Show ``image_path`` beside the looping ``video_path``, in gray.

        Either may be missing — a curated act is pinned in the overlay and has no
        past video under it, and a frame can have moved — and the plus shows only
        when both halves are there, since a lone picture is not a sum.
        """
        self._stop_movie()
        self._image_path = str(image_path) if image_path else None
        self._video_path = str(video_path) if video_path else None
        self._pixmap = _readable(self._image_path)
        if self._pixmap is None:
            self.image_label.clear()
        self.image_label.setVisible(self._pixmap is not None)
        has_video = bool(self._video_path and Path(self._video_path).is_file())
        if not has_video:
            self.video_label.clear()  # no stale last frame under the next pair
        self.video_label.setVisible(has_video)
        self.plus_label.setVisible(self._pixmap is not None and has_video)
        if has_video:
            self._movie = looping_movie(self._video_path, self._side_size(),
                                        self.video_label)
            play_grayscale(self._movie, self.video_label)
        self._rescale()

    def clear(self) -> None:
        """Drop both halves — the pane is showing something else now."""
        self._stop_movie()
        self._image_path = self._video_path = None
        self._pixmap = None
        self.image_label.clear()
        self.video_label.clear()

    # --- fitting ----------------------------------------------------------

    def _side(self) -> int:
        """The square each picture is fitted into: a share of the pane's height,
        but never more than half its width, so two of them plus the operator
        between them fit across however narrow the pane is dragged."""
        return max(1, min(int(self.height() * _HEIGHT_SHARE), self.width() // 2))

    def _side_size(self) -> QSize:
        side = self._side()
        return QSize(side, side)

    def _rescale(self) -> None:
        side = self._side()
        if self._pixmap is not None:
            self.image_label.setPixmap(self._pixmap.scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        if self._movie is not None and self._video_path:
            target = fit_size(self._video_path, QSize(side, side))
            if target is not None:
                # Re-fit in place rather than rebuilding: a new movie would restart
                # the loop from frame one on every pixel of a resize drag.
                self._movie.setScaledSize(target)
        font = self.plus_label.font()
        font.setPointSize(max(_MIN_PLUS_PT, int(side * _PLUS_SHARE)))
        self.plus_label.setFont(font)

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()
