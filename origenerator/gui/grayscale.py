from __future__ import annotations

from PySide6.QtGui import QImage, QPainter, QPixmap


def grayscale_pixmap(pixmap: QPixmap) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    source = pixmap.toImage()
    gray = source.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
        QImage.Format.Format_ARGB32
    )
    if source.hasAlphaChannel():
        # Qt: Format_Grayscale8 has no alpha, so the conversion back leaves every pixel opaque.
        painter = QPainter(gray)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, source)
        painter.end()
    return QPixmap.fromImage(gray)


def play_grayscale(movie, label) -> None:
    # Not QLabel.setMovie: the label would be handed the movie's own frames, in color.
    def show_frame(*_args):
        label.setPixmap(grayscale_pixmap(movie.currentPixmap()))

    movie.frameChanged.connect(show_frame)
    movie.start()
    show_frame()
