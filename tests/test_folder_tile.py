from __future__ import annotations

from PySide6.QtWidgets import QLabel

from origenerator import gallery
from origenerator.gui import folder_icons, tile_shape
from origenerator.gui.folder_tile import FolderMarks, FolderTile


def _label_texts(tile):
    return [w.text() for w in tile.findChildren(QLabel)]


def test_folder_tile_shows_its_folder_path_context(qtbot):
    tile = FolderTile("k", "a dog", [], 3, FolderMarks(context="Images \u203a SDXL"))
    qtbot.addWidget(tile)

    texts = _label_texts(tile)
    assert any("SDXL" in t for t in texts)
    assert "a dog" in texts


def test_a_path_too_long_for_the_tile_is_cut_from_the_front(qtbot):
    path = " › ".join(["Images", *(f"a folder with a long name {n}" for n in range(8)),
                            "the folder it sits in"])
    tile = FolderTile("k", "a dog", [], 3, FolderMarks(context=path))
    qtbot.addWidget(tile)

    shown = next(label.text() for label in tile.findChildren(QLabel) if label.toolTip() == path)
    assert shown != path
    assert shown.endswith("sits in"), (
        "the end of the path stays, since the folder this one sits in is what tells it from a "
        "folder of the same name elsewhere")


def test_folder_tile_without_context_omits_the_folder_path_line(qtbot):
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    texts = _label_texts(tile)
    assert "a dog" in texts
    assert all("\u203a" not in t for t in texts), (
        "a tile reached by drilling down has no path line: its siblings share a parent")


def test_folder_tile_shows_its_toc_initial(qtbot):
    tile = FolderTile("k", "wan model", [], 3, FolderMarks(
        kind_icon=folder_icons.folder_kind_icon(gallery.ModelGroup("k", "wan model", []))))
    qtbot.addWidget(tile)

    initials = [w for w in tile.findChildren(QLabel) if w.toolTip() == "Model"]
    assert initials, (
        "a model, LoRA or workflow tile wears the same TOC initial the tree does, so a folder's "
        "place in the hierarchy reads even in the mixed Favorites collection")
    assert not initials[0].pixmap().isNull()


def test_folder_tile_without_a_level_shows_no_toc_initial(qtbot):
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    assert all(w.toolTip() != "Model" for w in tile.findChildren(QLabel))


def test_a_folder_tile_is_the_same_tile_as_the_ones_it_stands_beside(qtbot):
    tile = FolderTile("k", "a dog", [], 3)
    qtbot.addWidget(tile)

    assert (tile.width(), tile.height()) == tile_shape.folder_tile_size()
    assert tile._thumbnails.size() == tile_shape.thumbnail_size()
    assert tile.layout().contentsMargins().left() == tile_shape.TILE_MARGIN
    assert tile_shape.idle_css("folderTile") in tile.styleSheet()


def test_the_folder_path_line_is_the_whole_of_what_makes_a_collection_tile_taller(qtbot):
    tile = FolderTile("k", "a dog", [], 3, FolderMarks(context="Images > SDXL"))
    qtbot.addWidget(tile)

    assert tile.height() == tile_shape.folder_tile_size(folder_path=True)[1]


def test_a_folder_square_wears_the_picked_frame_when_it_is_marked(qtbot):
    tile = FolderTile("image/sdxl_t2i/abc::landscape", "a folder", [], 3)
    qtbot.addWidget(tile)
    assert not tile._selected

    tile.set_selected(True)

    assert tile._selected, (
        "leaving a slideshow of All or Favorites lands on the folder the item came out of, "
        "because those show folders rather than the items inside them, so a folder's tile has "
        "to be able to show that it is the picked one")
    assert tile_shape.selected_css("folderTile") in tile.styleSheet()

    tile.set_selected(False)

    assert not tile._selected
    assert tile_shape.idle_css("folderTile") in tile.styleSheet()
