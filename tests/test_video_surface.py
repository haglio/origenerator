from __future__ import annotations

from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QApplication

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
