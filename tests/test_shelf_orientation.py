"""The special folders' Portrait / Landscape subfolders, and the Trash shelf.

A shelf collects generations of every shape at once, and a mixed set has no
one region to play on inside a hosting Fun Time session — so each collecting
shelf breaks down into a Portrait and a Landscape subfolder whose listing is
one shape, and whose slideshow therefore lands on one region.  The Trash
shelf is the other reviewability gap: what W and the up key culled used to
vanish into an undo stack nobody could see.
"""

from pathlib import Path

from PIL import Image
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui.gallery_tree import (
    RECENTS_KEY, STARRED_KEY, TRASH_KEY, TRASH_LABEL,
)
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.shelf_orientation import (
    filter_rows, oriented_key, row_orientation, split_key,
)

from tests.test_gallery_view import FakeDB, _image, _top_level


def _thumbed(row: dict, tmp_path: Path, width: int, height: int) -> dict:
    thumb = tmp_path / f"{row['prompt_id']}_thumb.png"
    Image.new("RGB", (width, height)).save(thumb)
    row["thumbnail_path"] = str(thumb)
    return row


def test_keys_split_and_join():
    assert oriented_key(RECENTS_KEY, "portrait") == "__recents__::portrait"
    assert split_key("__recents__::portrait") == (RECENTS_KEY, "portrait")
    assert split_key(RECENTS_KEY) == (RECENTS_KEY, None)
    assert split_key(None) == (None, None)
    assert split_key("__recents__::sideways") == ("__recents__::sideways", None)


def test_row_orientation_reads_the_stored_thumbnail(tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    assert row_orientation(tall) == "portrait"
    assert row_orientation(wide) == "landscape"
    assert filter_rows([tall, wide], "portrait") == [tall]
    assert filter_rows([tall, wide], "landscape") == [wide]
    assert filter_rows([tall, wide], None) == [tall, wide]


def test_an_unreadable_shape_files_under_landscape():
    # The same default the region routing uses for an unmeasurable set.
    bare = _image("b1", "scene three", 50, 3)  # no thumbnail, no file on disk
    assert row_orientation(bare) == "landscape"


def _children(item: QTreeWidgetItem) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_the_collecting_shelves_carry_orientation_subfolders(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    top = _top_level(view._tree)
    assert _children(top["Latest"]) == ["Portrait", "Landscape"]
    assert _children(top["Favorites"]) == ["Portrait", "Landscape"]
    assert _children(top["Experiments"]) == ["Portrait", "Landscape"]
    assert _children(top[TRASH_LABEL]) == []  # look-only; nothing plays from it


def test_a_subfolder_lists_and_plays_one_shape_only(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    portrait_item = view._item_by_key[oriented_key(RECENTS_KEY, "portrait")]
    view._tree.setCurrentItem(portrait_item)

    assert view._browser.visible_prompt_ids() == ["t1"]
    # The slideshow plays exactly the listing — a homogeneous set, so the
    # hosting session routes the whole show to the portrait region.
    assert [row["prompt_id"] for row in view._slideshow_rows()] == ["t1"]
    # And it is what history remembers, so Back returns to the subfolder.
    assert view._current_shelf_key() == oriented_key(RECENTS_KEY, "portrait")


def test_the_favorites_subfolder_covers_the_folders_items_too(qtbot, tmp_path):
    # A starred FOLDER's items count as the shelf's collection (the parent
    # shows the folder as a tile); its subfolders list them flat, filtered.
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    db = FakeDB([tall, wide])
    db.set_generation_starred("t1", True)
    db.set_generation_starred("w1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    landscape_item = view._item_by_key[oriented_key(STARRED_KEY, "landscape")]
    view._tree.setCurrentItem(landscape_item)

    assert view._browser.visible_prompt_ids() == ["w1"]
    assert [row["prompt_id"] for row in view._slideshow_rows()] == ["w1"]


def test_a_cull_lands_on_the_trash_shelf(qtbot, tmp_path):
    """W / the up key trashes what is on screen; the Trash shelf is where the
    culled item can then be SEEN — held by the recovery bin until it expires."""
    row = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    view.refresh()

    view._actions.delete_rows([row])
    view.refresh()

    assert [held["prompt_id"] for held in view._held_rows] == ["t1"]
    top = _top_level(view._tree)
    assert any(label.startswith(TRASH_LABEL) and "(1)" in label for label in top)

    trash_item = view._item_by_key[TRASH_KEY]
    view._tree.setCurrentItem(trash_item)  # renders look-only tiles, no crash
    assert view._current_shelf_key() == TRASH_KEY


def test_the_subfolders_are_visible_without_an_expander(qtbot):
    """A shelf row draws its marker IN the caret column, so it has no
    disclosure control to click — collapsed children simply do not exist on
    screen, which read as the subfolders not existing at all.  The shelves
    holding them are therefore expanded outright on every populate."""
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    top = _top_level(view._tree)
    assert top["Latest"].isExpanded()
    assert top["Favorites"].isExpanded()
    assert top["Experiments"].isExpanded()
