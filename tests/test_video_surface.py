from __future__ import annotations

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtMultimedia import QVideoFrame
from PyQt6.QtWidgets import QApplication

from origenerator.gui.video_surface import VideoSurface


def _frame(color: str) -> QVideoFrame:
    picture = QImage(64, 36, QImage.Format.Format_RGB32)
    picture.fill(QColor(color))
    return QVideoFrame(picture)


def _count_conversions(monkeypatch) -> list:
    converted = []
    to_image = QVideoFrame.toImage

    def counted(frame):
        converted.append(frame)
        return to_image(frame)

    monkeypatch.setattr(QVideoFrame, "toImage", counted)
    return converted


def test_a_burst_of_frames_costs_one_conversion_and_shows_the_newest(qtbot, monkeypatch):
    surface = VideoSurface()
    qtbot.addWidget(surface)
    surface.resize(64, 36)
    surface.show()
    qtbot.waitExposed(surface)
    converted = _count_conversions(monkeypatch)

    for color in ("red", "green", "blue", "yellow", "white"):
        surface.video_sink().setVideoFrame(_frame(color))
    QApplication.processEvents()

    assert len(converted) == 1
    assert surface.picture().pixelColor(32, 18) == QColor("white")
