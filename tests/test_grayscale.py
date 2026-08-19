"""Draining the color out of a picture shown only for what it configures."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap

from origenerator.gui.grayscale import grayscale_pixmap, play_grayscale


def _filled(color, side=8):
    image = QImage(side, side, QImage.Format.Format_ARGB32)
    image.fill(QColor(*color))
    return QPixmap.fromImage(image)


def test_a_colored_picture_comes_back_with_no_color_left(qapp):
    gray = grayscale_pixmap(_filled((200, 30, 30)))

    color = gray.toImage().pixelColor(4, 4)
    assert color.red() == color.green() == color.blue()


def test_light_and_dark_still_differ(qapp):
    # Drained, not flattened: a gray square would say nothing about the picture.
    light = grayscale_pixmap(_filled((240, 240, 240))).toImage().pixelColor(4, 4)
    dark = grayscale_pixmap(_filled((20, 20, 20))).toImage().pixelColor(4, 4)

    assert light.red() > dark.red() + 100


def test_a_transparent_edge_stays_cut_out(qapp):
    # Grayscale8 carries no alpha, so a naive conversion hands back a gray box
    # where the picture had a hole.
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(4, 4, QColor(200, 30, 30, 255))

    gray = grayscale_pixmap(QPixmap.fromImage(image)).toImage()

    assert gray.pixelColor(0, 0).alpha() == 0
    assert gray.pixelColor(4, 4).alpha() == 255


def test_a_null_pixmap_comes_back_as_it_went_in(qapp):
    # Callers treat a null as "no picture", not as an error to convert.
    assert grayscale_pixmap(QPixmap()).isNull()


def test_a_played_movie_paints_its_frames_gray_into_the_label(qtbot, tmp_path):
    from PIL import Image
    from PyQt6.QtGui import QMovie
    from PyQt6.QtWidgets import QLabel

    path = tmp_path / "clip.webp"
    frames = [Image.new("RGB", (16, 16), (200, 30, 30)) for _ in range(2)]
    frames[0].save(path, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    label = QLabel()
    qtbot.addWidget(label)
    movie = QMovie(str(path))
    movie.setParent(label)

    play_grayscale(movie, label)

    # The label carries pixmaps, not the movie: the movie's own frames arrive in
    # color and there is nowhere to intercept them once it owns the label.
    assert label.movie() is None
    color = label.pixmap().toImage().pixelColor(8, 8)
    assert color.red() == color.green() == color.blue()
    assert movie.state() == QMovie.MovieState.Running  # still looping, just drained
