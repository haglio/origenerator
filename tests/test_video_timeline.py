from __future__ import annotations

from player_core.timeline import BAR_BORDER, BAR_INSET_Y, BORDER_W, CURSOR_W
from PyQt6.QtGui import QColor

from origenerator.funscript import synthesize_actions
from origenerator.gui.video_timeline import VideoTimeline


def test_the_timeline_is_a_thin_fixed_height_track(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    assert 0 < timeline.height() <= 24
    assert timeline.minimumHeight() == timeline.maximumHeight()


def test_paints_without_error_scripted_and_empty(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(120, timeline.height())

    timeline.set_actions(synthesize_actions(3.0, hz=1.2))
    assert not timeline.grab().isNull()

    timeline.set_actions([])
    assert not timeline.grab().isNull()


def _cursor_x(timeline) -> float | None:
    image = timeline.grab().toImage()
    y = timeline.height() // 2
    xs = [x for x in range(timeline.width())
          if image.pixelColor(x, y) == QColor(255, 255, 255)]
    return sum(xs) / len(xs) if xs else None


def test_the_cursor_rides_the_videos_own_length(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions(synthesize_actions(4.0, hz=1.0))
    timeline.set_duration(8000)
    timeline.set_position(4000)
    assert abs(_cursor_x(timeline) - 50) <= 3
    image, y = timeline.grab().toImage(), timeline.height() // 2
    white = QColor(255, 255, 255)
    assert image.pixelColor(25, y) != white and image.pixelColor(75, y) != white


def test_an_unscripted_video_carries_the_cursor_too(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions([])
    timeline.set_duration(10000)
    timeline.set_position(5000)
    assert abs(_cursor_x(timeline) - 50) <= 3


def test_the_cursor_is_the_one_the_family_players_draw(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions([])
    timeline.set_duration(10000)
    timeline.set_position(5000)
    image = timeline.grab().toImage()
    white = QColor(255, 255, 255)
    y = timeline.height() // 2
    columns = [x for x in range(100) if image.pixelColor(x, y) == white]
    assert len(columns) == CURSOR_W
    assert all(image.pixelColor(columns[0], row) == white
               for row in (BAR_INSET_Y, timeline.height() - BAR_INSET_Y - 1))


def test_the_track_is_framed_the_way_the_players_frame_theirs(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions([])
    image = timeline.grab().toImage()
    border = QColor(*BAR_BORDER[:3])
    assert image.pixelColor(50, BAR_INSET_Y + BORDER_W - 1) == border
    assert image.pixelColor(50, timeline.height() // 2) != border


def test_a_new_script_starts_with_no_position(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions(synthesize_actions(4.0, hz=1.0))
    timeline.set_position(1000)
    timeline.set_actions(synthesize_actions(2.0, hz=1.0))
    assert timeline._position is None
    image = timeline.grab().toImage()
    y = timeline.height() // 2
    assert all(image.pixelColor(x, y) != QColor(255, 255, 255) for x in range(100))


def test_a_pane_with_no_room_for_a_track_draws_nothing(qtbot):
    narrow = 2 * BAR_INSET_Y + BORDER_W
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(narrow, timeline.height())
    timeline.set_actions([])
    timeline.set_duration(1000)
    timeline.set_position(500)
    bare = VideoTimeline()
    qtbot.addWidget(bare)
    bare.resize(narrow, bare.height())

    assert timeline.grab().toImage() == bare.grab().toImage()
