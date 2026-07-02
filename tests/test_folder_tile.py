from PyQt6.QtWidgets import QLabel

from origenerator.gui.folder_tile import FolderTile


def _label_texts(tile):
    return [w.text() for w in tile.findChildren(QLabel)]


def test_folder_tile_shows_its_breadcrumb_context(qtbot):
    # The Starred shelf captions each tile with where the folder lives, alongside
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
    # folder's place in the hierarchy reads even in the mixed Starred shelf.
    tile = FolderTile("k", "wan model", [], 3, level="model")
    qtbot.addWidget(tile)

    badges = [w for w in tile.findChildren(QLabel) if w.toolTip() == "Model"]
    assert badges and not badges[0].pixmap().isNull()


def test_folder_tile_without_a_level_shows_no_badge(qtbot):
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    assert all(w.toolTip() != "Model" for w in tile.findChildren(QLabel))
