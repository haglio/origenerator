from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from origenerator.gui import icons
from origenerator.gui.item_type_icon import ItemTypeIcon


def test_clicks_fall_through_the_icon_to_the_tile_beneath(qtbot):
    tile = QWidget()
    qtbot.addWidget(tile)
    icon = ItemTypeIcon("image", tile)
    assert icon.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), (
        "the mark is transparent to clicks, so selecting or opening the tile still works "
        "through it")


def test_the_icon_follows_the_kind_of_its_subject_when_that_changes(qtbot):
    tile = QWidget()
    qtbot.addWidget(tile)
    icon = ItemTypeIcon("image", tile)

    icon.set_media_type("video")

    assert (icon.media_type, icon.pixmap().toImage()) == (
        "video", icons.item_type_icon("video").toImage()), (
        "the Generate tab's source tile shows an image or a video in the one place, so its item "
        "type mark follows the kind it is handed rather than saying image over both")
