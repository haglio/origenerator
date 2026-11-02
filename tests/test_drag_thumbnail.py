from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QPointF, QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QLabel

from origenerator.gui.drag_thumbnail import (
    THUMBNAIL_MAX,
    DragOut,
    fit_thumbnail,
    label_thumbnail,
    set_drag_thumbnail,
)
from origenerator.gui.looping_preview import play_in


def _webp(path, size=(64, 48)):
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


class _RecordingDrag:
    def __init__(self):
        self.pixmap = None

    def setPixmap(self, pixmap):
        self.pixmap = pixmap


def test_a_big_thumbnail_shrinks_into_the_shared_size(qtbot):
    big = QPixmap(800, 600)
    big.fill()
    fitted = fit_thumbnail(big)
    assert fitted.width() == THUMBNAIL_MAX
    assert fitted.height() <= THUMBNAIL_MAX


def test_a_small_thumbnail_keeps_its_own_pixels(qtbot):
    small = QPixmap(96, 96)
    small.fill()
    assert fit_thumbnail(small).size() == QSize(96, 96)


def test_nothing_to_show_fits_to_nothing(qtbot):
    assert fit_thumbnail(None).isNull()
    assert fit_thumbnail(QPixmap()).isNull()


def test_a_label_playing_a_movie_offers_the_frame_it_is_on(qtbot, tmp_path):
    label = QLabel()
    qtbot.addWidget(label)
    movie = play_in(label, str(_webp(tmp_path / "v_anim.webp")), QSize(172, 160))
    movie.start()

    assert label.pixmap().isNull()
    assert not label_thumbnail(label).isNull()


def test_a_label_showing_a_still_offers_it(qtbot):
    label = QLabel()
    qtbot.addWidget(label)
    pixmap = QPixmap(200, 200)
    pixmap.fill()
    label.setPixmap(pixmap)

    assert label_thumbnail(label).width() == THUMBNAIL_MAX


def test_an_empty_label_offers_nothing(qtbot):
    label = QLabel("No preview")
    qtbot.addWidget(label)
    assert label_thumbnail(label).isNull()


def test_a_drag_with_a_thumbnail_wears_it(qtbot):
    pixmap = QPixmap(64, 64)
    pixmap.fill()
    drag = _RecordingDrag()
    set_drag_thumbnail(drag, pixmap)
    assert drag.pixmap is pixmap


def test_a_drag_with_no_thumbnail_is_left_bare(qtbot):
    drag = _RecordingDrag()
    set_drag_thumbnail(drag, QPixmap())
    assert drag.pixmap is None


class _Mouse:
    def __init__(self, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton):
        self._at, self._button, self._buttons = QPointF(x, y), button, buttons

    def position(self):
        return self._at

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons


def test_a_press_that_never_travels_the_drag_distance_stays_a_click(qtbot):
    gesture = DragOut()
    gesture.note_press(_Mouse(10, 10))

    assert not gesture.should_start(_Mouse(10, 10 + QApplication.startDragDistance() - 1))
    assert gesture.pressed


def test_one_press_starts_one_drag_once_it_travels_the_drag_distance(qtbot):
    gesture = DragOut()
    gesture.note_press(_Mouse(10, 10))
    past = _Mouse(10, 10 + QApplication.startDragDistance())

    assert gesture.should_start(past)
    assert not gesture.should_start(past)
    assert not gesture.pressed


def test_only_a_left_press_can_become_a_drag(qtbot):
    gesture = DragOut()
    gesture.note_press(_Mouse(10, 10, button=Qt.MouseButton.RightButton))

    assert not gesture.pressed


def test_a_gesture_has_no_qt_parent_to_take_it_down_with_its_widget(qtbot):
    assert DragOut().parent() is None
