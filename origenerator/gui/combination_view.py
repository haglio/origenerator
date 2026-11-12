from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMovie, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from shared_ui.colors import TEXT_MUTED
from shared_ui.icons import icon_pixmap
from shared_ui.spacing import MARGIN_STANDARD

from origenerator.gui.combination import (
    Combination,
    draw_plus,
    draw_source_video,
    pair_side,
    paren_font,
    paren_width,
    plus_width,
)
from origenerator.gui.looping_preview import fit_size, play_gray_in
from origenerator.gui.queue_thumbs import fitted_cell

_HEIGHT_SHARE = 0.8
_MARGIN = MARGIN_STANDARD


def combination_pixmap(combination: Combination, size: QSize) -> QPixmap | None:
    both = bool(combination.image and combination.source_video)
    enclosed = bool(combination.source_video) and combination.prompt_edited
    side = pair_side(size, both, enclosed)
    image = fitted_cell(combination.image, side)
    source_video = fitted_cell(combination.source_video, side, gray=True)
    if image is None and source_video is None:
        return None
    plus = plus_width(side) if image is not None and source_video is not None else 0
    paren = paren_width(side) if source_video is not None and enclosed else 0
    halves = sum(side for half in (image, source_video) if half is not None)
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
    if source_video is not None:
        draw_source_video(painter, x, source_video, enclosed)
    painter.end()
    return canvas


def _readable(path) -> QPixmap | None:
    if not path or not Path(path).is_file():
        return None
    pixmap = QPixmap(str(path))
    return None if pixmap.isNull() else pixmap


class CombinationView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_path: str | None = None
        self._video_path: str | None = None
        self._movie: QMovie | None = None
        self._pixmap: QPixmap | None = None
        self._has_video = False
        self._enclosed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(0)
        layout.addStretch(1)
        self.image_label = QLabel()
        self.plus_label = QLabel()
        self.open_paren_label = QLabel("(")
        self.video_label = QLabel()
        self.close_paren_label = QLabel(")")
        self._parens = (self.open_paren_label, self.close_paren_label)
        for operator in (self.plus_label, *self._parens):
            operator.setObjectName("mutedLabel")
        for paren in self._parens:
            paren.hide()
        for label in (self.image_label, self.plus_label, self.open_paren_label,
                      self.video_label, self.close_paren_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(label)
        layout.addStretch(1)

    def show_pair(self, combination: Combination) -> None:
        self._stop_movie()
        self._image_path = str(combination.image) if combination.image else None
        self._video_path = str(combination.source_video) if combination.source_video else None
        self._pixmap = _readable(self._image_path)
        if self._pixmap is None:
            self.image_label.clear()
        self.image_label.setVisible(self._pixmap is not None)
        self._has_video = bool(self._video_path and Path(self._video_path).is_file())
        if not self._has_video:
            self.video_label.clear()
        self.video_label.setVisible(self._has_video)
        self.plus_label.setVisible(self._pixmap is not None and self._has_video)
        self._show_parentheses(combination.prompt_edited)
        if self._has_video:
            self._movie = play_gray_in(self.video_label, self._video_path, self._side_size())
        self._rescale()

    def mark_prompt_edited(self, edited: bool) -> None:
        self._show_parentheses(edited)
        self._rescale()

    def _show_parentheses(self, edited: bool) -> None:
        self._enclosed = edited and self._has_video
        for paren in self._parens:
            paren.setVisible(self._enclosed)

    def clear(self) -> None:
        self._stop_movie()
        self._image_path = self._video_path = None
        self._pixmap = None
        self._has_video = self._enclosed = False
        self.image_label.clear()
        self.video_label.clear()

    def _side(self) -> int:
        room = QSize(self.width() - 2 * _MARGIN, int(self.height() * _HEIGHT_SHARE))
        return pair_side(room, self._pixmap is not None and self._has_video, self._enclosed)

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
                self._movie.setScaledSize(target)
        for label in (self.image_label, self.video_label):
            label.setFixedWidth(side)
        self.plus_label.setPixmap(icon_pixmap("plus", plus_width(side), TEXT_MUTED))
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
