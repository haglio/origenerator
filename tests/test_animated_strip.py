from PyQt6.QtCore import Qt

from origenerator.gui.animated_strip import AnimatedVideoStrip, _VideoTile


def test_strip_is_hidden_when_there_are_no_videos(qtbot):
    strip = AnimatedVideoStrip()
    qtbot.addWidget(strip)
    strip.show_videos([])
    assert strip.isHidden()


def test_strip_shows_one_tile_per_video_and_navigates_on_click(qtbot):
    strip = AnimatedVideoStrip()
    qtbot.addWidget(strip)
    activated = []
    strip.video_activated.connect(activated.append)

    strip.show_videos([("v1", None, None), ("v2", None, None)])
    strip.show()
    qtbot.waitExposed(strip)

    tiles = strip.findChildren(_VideoTile)
    assert len(tiles) == 2
    assert not strip.isHidden()

    qtbot.mouseClick(tiles[0], Qt.MouseButton.LeftButton)
    assert activated == ["v1"]


def test_show_videos_replaces_the_previous_tiles(qtbot):
    strip = AnimatedVideoStrip()
    qtbot.addWidget(strip)
    strip.show_videos([("v1", None, None), ("v2", None, None)])
    strip.show_videos([("v3", None, None)])  # a different image's animations
    assert len(strip.findChildren(_VideoTile)) == 1
