from __future__ import annotations

from funestra.scrubber_bar import BAR_BORDER, BAR_INSET_Y, BORDER_W, CURSOR_W
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from origenerator.funscript import synthesize_actions
from origenerator.gui.scrubber import Scrubber


def test_the_timeline_is_a_thin_fixed_height_track(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    assert 0 < scrubber.height() <= 24
    assert scrubber.minimumHeight() == scrubber.maximumHeight()


def test_paints_without_error_scripted_and_empty(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(120, scrubber.height())

    scrubber.set_actions(synthesize_actions(3.0, hz=1.2))
    assert not scrubber.grab().isNull()

    scrubber.set_actions([])
    assert not scrubber.grab().isNull()


def _cursor_x(scrubber) -> float | None:
    image = scrubber.grab().toImage()
    y = scrubber.height() // 2
    xs = [x for x in range(scrubber.width())
          if image.pixelColor(x, y) == QColor(255, 255, 255)]
    return sum(xs) / len(xs) if xs else None


def test_the_cursor_rides_the_videos_own_length(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(100, scrubber.height())
    scrubber.set_actions(synthesize_actions(4.0, hz=1.0))
    scrubber.set_duration(8000)
    scrubber.set_position(4000)
    assert abs(_cursor_x(scrubber) - 50) <= 3
    image, y = scrubber.grab().toImage(), scrubber.height() // 2
    white = QColor(255, 255, 255)
    assert image.pixelColor(25, y) != white
    assert image.pixelColor(75, y) != white


def test_an_unscripted_video_carries_the_cursor_too(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(100, scrubber.height())
    scrubber.set_actions([])
    scrubber.set_duration(10000)
    scrubber.set_position(5000)
    assert abs(_cursor_x(scrubber) - 50) <= 3


def test_the_cursor_is_the_one_the_family_funestras_draw(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(100, scrubber.height())
    scrubber.set_actions([])
    scrubber.set_duration(10000)
    scrubber.set_position(5000)
    image = scrubber.grab().toImage()
    white = QColor(255, 255, 255)
    y = scrubber.height() // 2
    columns = [x for x in range(100) if image.pixelColor(x, y) == white]
    assert len(columns) == CURSOR_W
    assert all(image.pixelColor(columns[0], row) == white
               for row in (BAR_INSET_Y, scrubber.height() - BAR_INSET_Y - 1))


def test_the_track_is_framed_the_way_the_funestras_frame_theirs(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(100, scrubber.height())
    scrubber.set_actions([])
    image = scrubber.grab().toImage()
    border = QColor(*BAR_BORDER[:3])
    assert image.pixelColor(50, BAR_INSET_Y + BORDER_W - 1) == border
    assert image.pixelColor(50, scrubber.height() // 2) != border


def test_a_new_script_starts_with_no_position(qtbot):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(100, scrubber.height())
    scrubber.set_actions(synthesize_actions(4.0, hz=1.0))
    scrubber.set_position(1000)
    scrubber.set_actions(synthesize_actions(2.0, hz=1.0))
    assert scrubber._position is None
    image = scrubber.grab().toImage()
    y = scrubber.height() // 2
    assert all(image.pixelColor(x, y) != QColor(255, 255, 255) for x in range(100))


def test_a_pane_with_no_room_for_a_track_draws_nothing(qtbot):
    narrow = 2 * BAR_INSET_Y + BORDER_W
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(narrow, scrubber.height())
    scrubber.set_actions([])
    scrubber.set_duration(1000)
    scrubber.set_position(500)
    bare = Scrubber()
    qtbot.addWidget(bare)
    bare.resize(narrow, bare.height())

    assert scrubber.grab().toImage() == bare.grab().toImage()


def _timed_scrubber(qtbot, *, duration_ms=10_000):
    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(100 + 2 * BAR_INSET_Y, scrubber.height())
    scrubber.set_duration(duration_ms)
    scrubber.set_position(0)
    heard = []
    scrubber.scrubbed.connect(heard.append)
    return scrubber, heard


def test_a_click_on_the_track_asks_for_the_moment_under_it(qtbot):
    scrubber, heard = _timed_scrubber(qtbot)

    qtbot.mousePress(scrubber, Qt.MouseButton.LeftButton,
                     pos=QPoint(BAR_INSET_Y + 50, scrubber.height() // 2))

    assert heard == [5000]


def test_a_drag_along_the_track_asks_for_each_moment_it_passes_and_the_cursor_follows(qtbot):
    scrubber, heard = _timed_scrubber(qtbot)
    y = scrubber.height() // 2

    qtbot.mousePress(scrubber, Qt.MouseButton.LeftButton, pos=QPoint(BAR_INSET_Y + 10, y))
    _drag_to(scrubber, QPoint(BAR_INSET_Y + 80, y))
    _drag_to(scrubber, QPoint(500, y))

    assert heard == [1000, 8000, 10_000]
    assert abs(_cursor_x(scrubber) - (scrubber.width() - BAR_INSET_Y)) <= CURSOR_W


def test_moving_over_the_track_without_holding_the_button_asks_for_nothing(qtbot):
    scrubber, heard = _timed_scrubber(qtbot)

    qtbot.mouseMove(scrubber, QPoint(BAR_INSET_Y + 50, scrubber.height() // 2))

    assert heard == []


def test_a_click_before_the_video_has_a_length_asks_for_nothing(qtbot):
    scrubber, heard = _timed_scrubber(qtbot, duration_ms=0)

    qtbot.mousePress(scrubber, Qt.MouseButton.LeftButton,
                     pos=QPoint(BAR_INSET_Y + 50, scrubber.height() // 2))

    assert heard == []


def _drag_to(scrubber, pos: QPoint) -> None:
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(scrubber.mapToGlobal(pos)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(scrubber, event)


def test_the_video_is_held_from_the_press_until_the_button_is_let_go(qtbot):
    scrubber, _heard = _timed_scrubber(qtbot)
    holds = []
    scrubber.held.connect(holds.append)
    y = scrubber.height() // 2

    qtbot.mousePress(scrubber, Qt.MouseButton.LeftButton, pos=QPoint(BAR_INSET_Y + 10, y))
    _drag_to(scrubber, QPoint(BAR_INSET_Y + 40, y))
    qtbot.mouseRelease(scrubber, Qt.MouseButton.LeftButton, pos=QPoint(BAR_INSET_Y + 40, y))

    assert holds == [True, False]
