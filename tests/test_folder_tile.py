from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from origenerator.gui import grid_card, icons
from origenerator.gui.folder_tile import FolderTile


def _label_texts(tile):
    return [w.text() for w in tile.findChildren(QLabel)]


def test_folder_tile_shows_its_breadcrumb_context(qtbot):
    # The Favorites shelf captions each tile with where the folder lives, alongside
    # the folder's own name, so two same-named folders stay tellable apart.
    tile = FolderTile("k", "a dog", [], 3, context="Images › SDXL")
    qtbot.addWidget(tile)

    texts = _label_texts(tile)
    assert any("SDXL" in t for t in texts)   # the breadcrumb line is shown
    assert "a dog" in texts                  # and the folder's own name


def test_folder_tile_without_context_omits_the_breadcrumb_line(qtbot):
    # A normal drill-down tile has no breadcrumb — its siblings share a parent.
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    texts = _label_texts(tile)
    assert "a dog" in texts
    assert all("›" not in t for t in texts)


def test_folder_tile_shows_its_recipe_level_badge(qtbot):
    # A model/LoRA/workflow tile wears the same lettered chip the tree does, so a
    # folder's place in the hierarchy reads even in the mixed Favorites shelf.
    tile = FolderTile("k", "wan model", [], 3, badge=icons.level_badge("model"))
    qtbot.addWidget(tile)

    badges = [w for w in tile.findChildren(QLabel) if w.toolTip() == "Model"]
    assert badges and not badges[0].pixmap().isNull()


def test_folder_tile_without_a_level_shows_no_badge(qtbot):
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    assert all(w.toolTip() != "Model" for w in tile.findChildren(QLabel))


def test_a_folder_tile_is_the_same_card_as_the_ones_it_stands_beside(qtbot):
    # Folder tiles and generation cards are laid into one flow, so a folder takes
    # the grid's width, picture area, margins and frame rather than numbers of its
    # own -- which is what had them standing a different height and a different
    # shade of border beside each other.
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    assert (tile.width(), tile.height()) == grid_card.folder_card_size()
    assert tile._collage.size() == grid_card.picture_size()
    assert tile.layout().contentsMargins().left() == grid_card.CARD_MARGIN
    assert grid_card.idle_css("folderTile") in tile.styleSheet()


def test_the_breadcrumb_line_is_the_whole_of_what_makes_a_shelf_tile_taller(qtbot):
    # The Favorites shelf's tiles carry one line the others do not, so their height
    # is the same card plus exactly that line.
    tile = FolderTile("k", "a dog", [], 3, context="Images > SDXL")
    qtbot.addWidget(tile)

    assert tile.height() == grid_card.folder_card_size(breadcrumb=True)[1]
