"""The two halves of a combination, shown as the sum they are: image + recipe.

What "Open in generator" hands a tab is not a generation — it is a picture and a
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

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtGui import QPixmap, QMovie
from PyQt6.QtCore import Qt, QSize

from origenerator.gui.grayscale import play_grayscale
from origenerator.gui.looping_preview import fit_size, looping_movie

# How much of the pane's height a picture takes, leaving room for the plus sign
# to breathe between them and the pane's own margins around them.
_HEIGHT_SHARE = 0.8
# The plus, as a fraction of a picture's side — big enough to read as the operator
# joining them rather than as a mark on one of the pictures.
_PLUS_SHARE = 0.28
_MIN_PLUS_PT = 12


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
        past video behind it, and a frame can have moved — and the plus shows only
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
