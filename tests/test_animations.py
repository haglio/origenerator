from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from origenerator.gui.animations import Animations, _VideoTile


def test_animations_are_hidden_when_there_are_no_videos(qtbot):
    animations = Animations()
    qtbot.addWidget(animations)
    animations.show_videos([])
    assert animations.isHidden()


def test_animations_show_one_tile_per_video_and_navigate_on_click(qtbot):
    animations = Animations()
    qtbot.addWidget(animations)
    activated = []
    animations.video_activated.connect(activated.append)

    animations.show_videos([("v1", None, None), ("v2", None, None)])
    with qtbot.waitExposed(animations):
        animations.show()

    tiles = animations.findChildren(_VideoTile)
    assert len(tiles) == 2
    assert not animations.isHidden()

    qtbot.mouseClick(tiles[0], Qt.MouseButton.LeftButton)
    assert activated == ["v1"]


def test_show_videos_replaces_the_previous_tiles(qtbot):
    animations = Animations()
    qtbot.addWidget(animations)
    animations.show_videos([("v1", None, None), ("v2", None, None)])
    animations.show_videos([("v3", None, None)])  # a different image's animations
    assert len(animations.findChildren(_VideoTile)) == 1


def test_the_previews_sit_right_under_the_animations_title_with_no_heading_between(qtbot):
    animations = Animations()
    qtbot.addWidget(animations)
    animations.show_videos([("v1", None, None)])
    assert [label.text() for label in animations.findChildren(QLabel) if label.text()] == []


def test_a_heading_shows_only_while_a_video_names_what_its_starting_frame_became(qtbot):
    animations = Animations()
    qtbot.addWidget(animations)
    animations.show_videos([("v1", None, None)])
    animations.set_heading("Starting frame animated in")
    shown = animations._heading.text() if not animations._heading.isHidden() else None
    animations.set_heading("")
    assert (shown, animations._heading.isHidden()) == ("Starting frame animated in", True)
