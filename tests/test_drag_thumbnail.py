"""The picture every drag hangs under the cursor, however its source shows it."""

from PIL import Image
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel

from origenerator.gui.drag_thumbnail import (
    THUMBNAIL_BOX, fit_thumbnail, label_thumbnail, set_drag_thumbnail,
)
from origenerator.gui.looping_preview import looping_movie


def _webp(path, size=(64, 48)):
    """A tiny two-frame looping WebP, the shape a video thumbnail animates."""
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


class _RecordingDrag:
    """Stands in for QDrag, remembering whether a picture was hung on it."""

    def __init__(self):
        self.pixmap = None

    def setPixmap(self, pixmap):
        self.pixmap = pixmap


def test_a_big_picture_shrinks_into_the_shared_box(qtbot):
    # A preview pane's still is the size of the pane; under the cursor it is a
    # thumbnail, the same as one dragged from anywhere else.
    big = QPixmap(800, 600)
    big.fill()
    fitted = fit_thumbnail(big)
    assert fitted.width() == THUMBNAIL_BOX
    assert fitted.height() <= THUMBNAIL_BOX


def test_a_small_picture_keeps_its_own_pixels(qtbot):
    # Only ever shrinks: blowing a 96px version tile up to the box would just
    # make it soft.
    small = QPixmap(96, 96)
    small.fill()
    assert fit_thumbnail(small).size() == QSize(96, 96)


def test_nothing_to_show_fits_to_nothing(qtbot):
    assert fit_thumbnail(None).isNull()
    assert fit_thumbnail(QPixmap()).isNull()


def test_a_label_playing_a_movie_offers_the_frame_it_is_on(qtbot, tmp_path):
    # The case that used to come up empty: a label with a movie has a null
    # pixmap(), so a video tile asked the wrong way trailed nothing.
    label = QLabel()
    qtbot.addWidget(label)
    movie = looping_movie(str(_webp(tmp_path / "v_anim.webp")), QSize(172, 160), label)
    label.setMovie(movie)
    movie.start()

    assert label.pixmap().isNull()          # the label itself has none
    assert not label_thumbnail(label).isNull()  # but the movie's frame is a picture


def test_a_label_showing_a_still_offers_it(qtbot):
    label = QLabel()
    qtbot.addWidget(label)
    pixmap = QPixmap(200, 200)
    pixmap.fill()
    label.setPixmap(pixmap)

    assert label_thumbnail(label).width() == THUMBNAIL_BOX


def test_an_empty_label_offers_nothing(qtbot):
    label = QLabel("No preview")
    qtbot.addWidget(label)
    assert label_thumbnail(label).isNull()


def test_a_drag_with_a_picture_wears_it(qtbot):
    pixmap = QPixmap(64, 64)
    pixmap.fill()
    drag = _RecordingDrag()
    set_drag_thumbnail(drag, pixmap)
    assert drag.pixmap is pixmap


def test_a_drag_with_no_picture_is_left_bare(qtbot):
    # An empty box following the cursor says less than the plain drag cursor.
    drag = _RecordingDrag()
    set_drag_thumbnail(drag, QPixmap())
    assert drag.pixmap is None
