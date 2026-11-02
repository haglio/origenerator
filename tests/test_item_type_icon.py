from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from origenerator.gui import icons
from origenerator.gui.item_type_icon import ItemTypeIcon


def test_clicks_fall_through_the_icon_to_the_tile_beneath(qtbot):
    tile = QWidget()
    qtbot.addWidget(tile)
    icon = ItemTypeIcon("image", tile)
    assert icon.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_the_icon_follows_the_kind_of_its_subject_when_that_changes(qtbot):
    tile = QWidget()
    qtbot.addWidget(tile)
    icon = ItemTypeIcon("image", tile)

    icon.set_media_type("video")

    assert icon.media_type == "video"
    assert icon.pixmap().toImage() == icons.item_type_icon("video").toImage()
