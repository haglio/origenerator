"""Drain the color out of a picture shown only for what it configures.

A video dropped into the combine panel is not what is being made — it is the
recipe the run will follow. In full color beside the frame it will animate it
reads as a second subject, and a queue row showing it alone reads as a job that
is that video. Gray says outright that it is a setting rather than a result, so
every surface a config-only video reaches — the combine slot, the queue row's
picture block, and the pane a combination opens in — draws it through here.

Alpha is carried across rather than flattened, so a picture with a cut-out edge
stays cut out instead of gaining a gray box around it.
"""

from PyQt6.QtGui import QImage, QPainter, QPixmap


def grayscale_pixmap(pixmap: QPixmap) -> QPixmap:
    """``pixmap`` desaturated, keeping its alpha channel.

    A null pixmap comes back as it went in — there is nothing to drain, and the
    callers all treat a null as "no picture" rather than as an error.
    """
    if pixmap.isNull():
        return pixmap
    source = pixmap.toImage()
    gray = source.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
        QImage.Format.Format_ARGB32
    )
    if source.hasAlphaChannel():
        # Grayscale8 has no alpha, so the conversion back to ARGB32 leaves every
        # pixel opaque. Painting the original over it in DestinationIn keeps the
        # gray and takes the alpha from the source.
        painter = QPainter(gray)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, source)
        painter.end()
    return QPixmap.fromImage(gray)


def play_grayscale(movie, label) -> None:
    """Loop ``movie`` into ``label``, every frame drained on its way through.

    Not ``QLabel.setMovie``: that hands the label the movie's own frames, which
    arrive in color with nowhere to intercept them. Pushing each frame across as
    a pixmap costs one conversion per frame at thumbnail size — nothing beside
    decoding the frame in the first place.

    The first frame is drawn on the spot rather than waited for: ``start()`` has
    already made it current, and a tile that stayed blank until the movie's next
    tick would flicker in on arrival.
    """
    def show_frame(*_args):
        label.setPixmap(grayscale_pixmap(movie.currentPixmap()))

    movie.frameChanged.connect(show_frame)
    movie.start()
    show_frame()
