from __future__ import annotations

from player_core.timeline import BAR_BORDER, BAR_INSET_Y, BORDER_W, CURSOR_W
from PyQt6.QtGui import QColor

from origenerator.funscript import synthesize_actions
from origenerator.gui.video_timeline import VideoTimeline


def test_the_timeline_is_a_thin_fixed_height_track(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    assert 0 < timeline.height() <= 24
    assert timeline.minimumHeight() == timeline.maximumHeight()  # fixed, doesn't grow


def test_paints_without_error_scripted_and_empty(qtbot):
    # grab() forces a paint into a pixmap — a smoke test that paintEvent runs for
    # both a scripted timeline (heatmap) and an unscripted one (plain track).
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(120, timeline.height())

    timeline.set_actions(synthesize_actions(3.0, hz=1.2, loop=False))
    assert not timeline.grab().isNull()

    timeline.set_actions([])
    assert not timeline.grab().isNull()


def _cursor_x(timeline) -> float | None:
    """Where the white cursor sits across the timeline, or None where none is drawn."""
    image = timeline.grab().toImage()
    y = timeline.height() // 2
    xs = [x for x in range(timeline.width())
          if image.pixelColor(x, y) == QColor(255, 255, 255)]
    return sum(xs) / len(xs) if xs else None


def test_the_cursor_rides_the_videos_own_length(qtbot):
    # Four seconds into an eight-second video is halfway along, however far into
    # the video its script happens to run. The video's length is the axis because
    # the cursor's jump back to the left IS the loop -- read off the script's
    # span instead, a video whose script stops early loops early on the timeline.
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions(synthesize_actions(4.0, hz=1.0, loop=False))
    timeline.set_duration(8000)
    timeline.set_position(4000)
    assert abs(_cursor_x(timeline) - 50) <= 3
    image, y = timeline.grab().toImage(), timeline.height() // 2
    white = QColor(255, 255, 255)
    assert image.pixelColor(25, y) != white and image.pixelColor(75, y) != white


def test_an_unscripted_video_carries_the_cursor_too(qtbot):
    # The motion heatmap is the fill, not the point: a video with no script is
    # a plain track, and it says where playback is like any other.
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions([])
    timeline.set_duration(10000)
    timeline.set_position(5000)
    assert abs(_cursor_x(timeline) - 50) <= 3


def test_the_cursor_is_the_one_the_family_players_draw(qtbot):
    # The same width, and the full height of the track, as the mark the
    # players ride along a video's lower edge: a hairline was there all along
    # and read as part of the heatmap rather than as where the video is.
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
    # Floated off the pane's edges inside a light border. A video that barely
    # moves paints a near-black heatmap, and unframed that reads as a gap
    # below the video rather than as the video's own length.
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions([])
    image = timeline.grab().toImage()
    border = QColor(*BAR_BORDER[:3])
    assert image.pixelColor(50, BAR_INSET_Y + BORDER_W - 1) == border
    assert image.pixelColor(50, timeline.height() // 2) != border  # the fill inside it


def test_a_new_script_starts_with_no_position(qtbot):
    timeline = VideoTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(100, timeline.height())
    timeline.set_actions(synthesize_actions(4.0, hz=1.0, loop=False))
    timeline.set_position(1000)
    timeline.set_actions(synthesize_actions(2.0, hz=1.0, loop=False))
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
