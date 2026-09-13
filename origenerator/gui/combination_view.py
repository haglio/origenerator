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
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QMovie, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from origenerator.gui.combination import (
    Combination,
    draw_plus,
    draw_recipe,
    pair_side,
    paren_font,
    paren_width,
    plus_font,
    plus_width,
)
from origenerator.gui.grayscale import play_grayscale
from origenerator.gui.looping_preview import fit_size, looping_movie
from origenerator.gui.queue_thumbs import fitted_cell

# How much of the pane's height a picture takes, leaving room for the plus sign
# to breathe between them and the pane's own margins around them.
_HEIGHT_SHARE = 0.8
_MARGIN = 8


def combination_pixmap(combination: Combination, size: QSize) -> QPixmap | None:
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
    both = bool(combination.picture and combination.recipe)
    enclosed = bool(combination.recipe) and combination.recipe_prompt_edited
    side = pair_side(size, both, enclosed)
    image = fitted_cell(combination.picture, side)
    recipe = fitted_cell(combination.recipe, side, gray=True)
    if image is None and recipe is None:
        return None
    plus = plus_width(side) if image is not None and recipe is not None else 0
    paren = paren_width(side) if recipe is not None and enclosed else 0
    halves = sum(side for half in (image, recipe) if half is not None)
    canvas = QPixmap(halves + plus + 2 * paren, side)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    x = 0
    if image is not None:
        painter.drawPixmap(0, 0, image)
        x = side
    if plus:
        draw_plus(painter, x, side)
        x += plus
    if recipe is not None:
        draw_recipe(painter, x, recipe, enclosed)
    painter.end()
    return canvas


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
        self._has_clip = False
        self._enclosed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(0)
        layout.addStretch(1)
        self.image_label = QLabel()
        self.plus_label = QLabel("+")
        self.open_paren_label = QLabel("(")
        self.video_label = QLabel()
        self.close_paren_label = QLabel(")")
        self._parens = (self.open_paren_label, self.close_paren_label)
        for operator in (self.plus_label, *self._parens):
            operator.setObjectName("estimateLabel")  # muted, like the pane's own text
        for paren in self._parens:
            paren.hide()
        # Clicks fall through to the pane, which owns the double-click that opens
        # a show — there is nothing here to open, so nothing here should eat one.
        for label in (self.image_label, self.plus_label, self.open_paren_label,
                      self.video_label, self.close_paren_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(label)
        layout.addStretch(1)

    def show_pair(self, combination: Combination) -> None:
        """Show the picture beside its recipe clip, looping in gray.

        Either may be missing — a curated act is pinned in the overlay and has no
        past video under it, and a frame can have moved — and the plus shows only
        when both halves are there, since a lone picture is not a sum.
        """
        self._stop_movie()
        self._image_path = str(combination.picture) if combination.picture else None
        self._video_path = str(combination.recipe) if combination.recipe else None
        self._pixmap = _readable(self._image_path)
        if self._pixmap is None:
            self.image_label.clear()
        self.image_label.setVisible(self._pixmap is not None)
        self._has_clip = bool(self._video_path and Path(self._video_path).is_file())
        if not self._has_clip:
            self.video_label.clear()  # no stale last frame under the next pair
        self.video_label.setVisible(self._has_clip)
        self.plus_label.setVisible(self._pixmap is not None and self._has_clip)
        self._show_parentheses(combination.recipe_prompt_edited)
        if self._has_clip:
            self._movie = looping_movie(self._video_path, self._side_size(),
                                        self.video_label)
            play_grayscale(self._movie, self.video_label)
        self._rescale()

    def mark_recipe_prompt_edited(self, edited: bool) -> None:
        self._show_parentheses(edited)
        self._rescale()

    def _show_parentheses(self, edited: bool) -> None:
        self._enclosed = edited and self._has_clip
        for paren in self._parens:
            paren.setVisible(self._enclosed)

    def clear(self) -> None:
        """Drop both halves — the pane is showing something else now."""
        self._stop_movie()
        self._image_path = self._video_path = None
        self._pixmap = None
        self._has_clip = self._enclosed = False
        self.image_label.clear()
        self.video_label.clear()

    # --- fitting ----------------------------------------------------------

    def _side(self) -> int:
        """The square each picture is fitted into: a share of the pane's height,
        and no wider than lets the pair, its plus and any parentheses fit across
        between the margins — the arithmetic :func:`combination_pixmap` draws by."""
        room = QSize(self.width() - 2 * _MARGIN, int(self.height() * _HEIGHT_SHARE))
        return pair_side(room, self._pixmap is not None and self._has_clip, self._enclosed)

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
        for picture in (self.image_label, self.video_label):
            picture.setFixedWidth(side)
        self.plus_label.setFont(plus_font(self.plus_label.font(), side))
        self.plus_label.setFixedWidth(plus_width(side))
        for paren in self._parens:
            paren.setFont(paren_font(paren.font(), side))
            paren.setFixedWidth(paren_width(side))

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()
