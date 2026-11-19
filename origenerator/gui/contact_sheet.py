from __future__ import annotations

import math
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QUrl
from PySide6.QtGui import QImageReader, QPainter, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QWidget

from origenerator.gui import omnipause
from origenerator.gui.video_surface import VideoSurface, release_media_player
from origenerator.media import MediaType, ShownFile

SQUARE = 1.0


def rows_for(count: int, width: int, height: int, *, shape: float) -> int:
    if count <= 0 or width <= 0 or height <= 0:
        return 0
    best = None
    for rows in range(1, count + 1):
        cell_shape = (width / math.ceil(count / rows)) / (height / rows)
        mismatch = abs(math.log(cell_shape / shape))
        if best is None or mismatch < best[0]:
            best = (mismatch, rows)
    return best[1]


def shape_of(sizes: list[QSize]) -> float:
    known = [size for size in sizes if size.isValid() and not size.isEmpty()]
    if not known:
        return SQUARE
    return math.exp(sum(math.log(s.width() / s.height()) for s in known) / len(known))


def row_counts(count: int, rows: int) -> list[int]:
    if rows <= 0 or count <= 0:
        return []
    base, extra = divmod(count, rows)
    return [base + 1] * extra + [base] * (rows - extra)


def fitted_into(cell: QRect, size: QSize) -> QRect:
    if not size.isValid() or size.isEmpty():
        return cell
    fitted = QRect(QPoint(), size.scaled(cell.size(), Qt.AspectRatioMode.KeepAspectRatio))
    fitted.moveCenter(cell.center())
    return fitted


def _is_file(path) -> bool:
    return bool(path) and Path(path).is_file()


class _Image(NamedTuple):
    pixmap: QPixmap

    def size(self) -> QSize:
        return self.pixmap.size()


class _Video(NamedTuple):
    player: QMediaPlayer
    surface: VideoSurface
    shape: QSize

    def size(self) -> QSize:
        return self.shape


class ContactSheet(QWidget):
    def __init__(self, parent=None, *, make_player=QMediaPlayer):
        super().__init__(parent)
        self._make_player = make_player
        self._shown: list[_Image | _Video] = []
        omnipause.holds(self)

    def show_files(self, files) -> None:
        self.clear()
        self._shown = [shown for file in files if (shown := self._readable(file)) is not None]
        self._place_the_videos()
        self.update()

    def _readable(self, file: ShownFile) -> _Image | _Video | None:
        if not _is_file(file.path):
            return None
        if file.media_type == MediaType.VIDEO:
            return self._playing(file)
        pixmap = QPixmap(str(file.path))
        return None if pixmap.isNull() else _Image(pixmap)

    def _playing(self, file: ShownFile) -> _Video:
        surface = VideoSurface(self)
        surface.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        player = self._make_player(self)
        player.setVideoOutput(surface.video_sink())
        player.setLoops(QMediaPlayer.Loops.Infinite)
        player.setSource(QUrl.fromLocalFile(str(Path(file.path))))
        if not omnipause.frozen():
            player.play()
        surface.show()
        shape = QImageReader(str(file.thumbnail)).size() if _is_file(file.thumbnail) else QSize()
        return _Video(player, surface, shape)

    def clear(self) -> None:
        for shown in self._shown:
            if isinstance(shown, _Video):
                release_media_player(shown.player)
                shown.player.deleteLater()
                shown.surface.deleteLater()
        self._shown = []
        self.update()

    def set_frozen(self, frozen: bool) -> None:
        for shown in self._shown:
            if isinstance(shown, _Video):
                if frozen:
                    shown.player.pause()
                else:
                    shown.player.play()

    def count(self) -> int:
        return len(self._shown)

    def cells(self) -> list[QRect]:
        if not self._shown:
            return []
        rows = rows_for(len(self._shown), self.width(), self.height(),
                        shape=shape_of([shown.size() for shown in self._shown]))
        laid = []
        for row, columns in enumerate(row_counts(len(self._shown), rows)):
            top = round(row * self.height() / rows)
            lower = round((row + 1) * self.height() / rows)
            for column in range(columns):
                left = round(column * self.width() / columns)
                right = round((column + 1) * self.width() / columns)
                laid.append(QRect(left, top, right - left, lower - top))
        return laid

    def _place_the_videos(self) -> None:
        for shown, cell in zip(self._shown, self.cells(), strict=True):
            if isinstance(shown, _Video):
                shown.surface.setGeometry(fitted_into(cell, shown.shape))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_the_videos()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for shown, cell in zip(self._shown, self.cells(), strict=True):
            if isinstance(shown, _Image):
                painter.drawPixmap(fitted_into(cell, shown.pixmap.size()), shown.pixmap)
