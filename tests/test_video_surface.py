from __future__ import annotations

from app_support.threading_utils import wait_until
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QApplication, QWidget

from origenerator import ui_scale
from origenerator.gui.video_surface import VideoSurface


def _frame(color: str) -> QVideoFrame:
    pixels = QImage(64, 36, QImage.Format.Format_RGB32)
    pixels.fill(QColor(color))
    return QVideoFrame(pixels)


def _count_conversions(monkeypatch) -> list:
    converted = []
    to_image = QVideoFrame.toImage

    def counted(frame):
        converted.append(frame)
        return to_image(frame)

    monkeypatch.setattr(QVideoFrame, "toImage", counted)
    return converted


def test_frames_drawn_cost_the_window_thread_no_conversion(qtbot, monkeypatch):
    surface = VideoSurface()
    qtbot.addWidget(surface)
    surface.resize(64, 36)
    with qtbot.waitExposed(surface):
        surface.show()
    converted = _count_conversions(monkeypatch)

    for color in ("red", "green", "blue", "yellow", "white"):
        surface.video_sink().setVideoFrame(_frame(color))
        surface.grab()
        QApplication.processEvents()

    assert converted == []


def test_the_frame_on_screen_is_the_newest_one_handed_over(qtbot):
    surface = VideoSurface()
    qtbot.addWidget(surface)

    for color in ("red", "green", "white"):
        surface.video_sink().setVideoFrame(_frame(color))

    assert surface.current_frame().pixelColor(32, 18) == QColor("white")


class _PaintsSeen(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.painted = []

    def paintEvent(self, event):
        self.painted.append(event.rect())


def _a_window_with_a_video_redrawn_away_from_its_top_left(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    top_left = _PaintsSeen(window)
    top_left.setGeometry(0, 0, 20, 20)
    away = _PaintsSeen(window)
    away.setGeometry(200, 200, 100, 20)
    VideoSurface(window).setGeometry(0, 300, 160, 90)
    window.resize(400, 400)
    window.show()
    wait_until(lambda: bool(top_left.painted and away.painted), pump=QApplication.processEvents)
    top_left.painted.clear()
    away.painted.clear()
    away.update()
    wait_until(lambda: bool(away.painted), pump=QApplication.processEvents)
    return top_left.painted


def test_in_fun_time_every_redraw_reaches_the_screen_from_the_windows_top_left(qtbot):
    ui_scale.draw_at(ui_scale.HOSTED_SCALE)

    assert _a_window_with_a_video_redrawn_away_from_its_top_left(qtbot)


def test_standalone_a_redraw_leaves_the_windows_top_left_alone(qtbot):
    assert _a_window_with_a_video_redrawn_away_from_its_top_left(qtbot) == []
