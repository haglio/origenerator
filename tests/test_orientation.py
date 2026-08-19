"""Two copies of the whole table of contents, one per shape.

A mixed-shape set has no one screen to play on, so the tree is rooted on a
Portrait row and a Landscape row and each carries the ENTIRE table of contents
over its own shape's rows: the shelves, the folders the user composed, and the
All row over the library.  Standing anywhere is standing on one shape, so a
slideshow started there has exactly one region to go to — and which one is read
off the key rather than measured back out of the items.
"""

from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY, RECENTS_KEY, REQUESTS_KEY, STARRED_KEY, TRASH_KEY, TRASH_LABEL,
)
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.orientation import (
    ROOT_KEY, base_of, filter_rows, orientation_of, oriented_key, root_key,
    row_orientation, split_key, split_rows,
)

from tests.test_gallery_view import FakeDB, _image, _row, _side_rows


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
    assert base_of("image/sdxl_t2i/m0011::portrait") == "image/sdxl_t2i/m0011"
    assert orientation_of("image/sdxl_t2i/m0011::portrait") == "portrait"
    assert root_key("landscape") == oriented_key(ROOT_KEY, "landscape")


def test_row_orientation_reads_the_stored_thumbnail(tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    assert row_orientation(tall) == "portrait"
    assert row_orientation(wide) == "landscape"
    assert filter_rows([tall, wide], "portrait") == [tall]
    assert filter_rows([tall, wide], "landscape") == [wide]
    assert filter_rows([tall, wide], None) == [tall, wide]
    assert split_rows([tall, wide]) == {"portrait": [tall], "landscape": [wide]}


def test_a_generation_with_no_picture_yet_goes_by_the_size_it_asked_for():
    """Its folder joins the tree the moment it starts running, and it has to
    join on the side the picture will land on rather than move there later."""
    cooking = _row("c1", "sdxl_t2i",
                   {"positive_prompt": "scene three", "width": 720, "height": 1280},
                   "sdxl_t2i_c1.png")  # nothing on disk yet, so only the size answers
    assert row_orientation(cooking) == "portrait"


def test_an_unreadable_shape_files_under_landscape():
    # The same default the region routing uses for an unmeasurable set.
    bare = _image("b1", "scene three", 50, 3)  # no thumbnail, no file, no size
    assert row_orientation(bare) == "landscape"


def _children(item: QTreeWidgetItem) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def _roots(tree) -> dict:
    return {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())}


def test_the_tree_is_rooted_on_the_two_shapes(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    roots = _roots(view._tree)
    assert list(roots) == ["Portrait", "Landscape"]
    # Each root carries the whole table of contents, not a slice of it.
    for side in ("Portrait", "Landscape"):
        assert _children(roots[side]) == [
            "Latest", "Favorites", "Experiments", "Requests", "Trash", "All",
        ]


def test_both_roots_are_drawn_even_for_a_shape_with_nothing_in_it(qtbot, tmp_path):
    """The split is what tells a slideshow which screen it is for, so the side
    you have not generated for yet is still somewhere you can stand."""
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([wide]))
    qtbot.addWidget(view)
    view.refresh()

    roots = _roots(view._tree)
    assert list(roots) == ["Portrait", "Landscape"]
    # No folders of that shape yet, so no Favorites and no library — but the
    # shelves a first generation would land on are all there.
    assert _children(roots["Portrait"]) == ["Experiments", "Requests", "Trash"]
    assert "All" in _children(roots["Landscape"])


def test_a_root_is_a_header_rather_than_a_place_to_stand(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    root = _roots(view._tree)["Portrait"]
    assert not (root.flags() & Qt.ItemFlag.ItemIsSelectable)
    assert root.isExpanded()  # everything it holds is visible without a click


def test_each_side_holds_only_its_own_shape(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    assert _side_rows(view, "portrait") == ["t1"]
    assert _side_rows(view, "landscape") == ["w1"]


def test_a_shelf_belongs_to_one_side(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._item_by_key[oriented_key(RECENTS_KEY, "portrait")])

    assert view._browser.visible_prompt_ids() == ["t1"]
    # The slideshow plays exactly the listing — a homogeneous set, so the
    # hosting session routes the whole show to the portrait region.
    assert [row["prompt_id"] for row in view._slideshow_rows()] == ["t1"]
    # And it is what history remembers, so Back returns to that side's shelf.
    assert view._current_shelf_key() == oriented_key(RECENTS_KEY, "portrait")


def test_favorites_collects_the_bookmarks_of_its_own_side(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    db = FakeDB([tall, wide])
    db.set_generation_starred("t1", True)
    db.set_generation_starred("w1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._item_by_key[oriented_key(STARRED_KEY, "landscape")])

    assert view._browser.visible_prompt_ids() == ["w1"]
    assert [row["prompt_id"] for row in view._slideshow_rows()] == ["w1"]


def test_the_trash_and_requests_shelves_split_too(qtbot, tmp_path):
    """The half-measure this replaces left Requests, Trash and All whole; the
    whole table of contents means the whole of it."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    view._actions.delete_rows([tall, wide])
    view.refresh()

    assert sorted(held["prompt_id"] for held in view._held_rows) == ["t1", "w1"]
    roots = _roots(view._tree)
    assert f"{TRASH_LABEL} (1)" in _children(roots["Portrait"])
    assert f"{TRASH_LABEL} (1)" in _children(roots["Landscape"])

    view._tree.setCurrentItem(view._item_by_key[oriented_key(TRASH_KEY, "portrait")])
    assert view._current_shelf_key() == oriented_key(TRASH_KEY, "portrait")
    assert [row["prompt_id"] for row in view._slideshow_rows()] == ["t1"]

    assert view._browser.rows_for_shelf(oriented_key(REQUESTS_KEY, "portrait")) == []


def test_a_side_counts_only_its_own_waiting_work(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    tall["source"] = "experiment"
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    wide["source"] = "experiment"
    other = _thumbed(_image("w2", "scene four", 50, 3), tmp_path, 160, 90)
    other["source"] = "experiment"
    view = GalleryView(FakeDB([tall, wide, other]))
    qtbot.addWidget(view)
    view.refresh()

    roots = _roots(view._tree)
    assert "Experiments (1)" in _children(roots["Portrait"])
    assert "Experiments (2)" in _children(roots["Landscape"])


def test_the_shelves_are_visible_without_an_expander(qtbot, tmp_path):
    """A side root's children have to be on screen: the split is the first thing
    the tree says, and a collapsed root says none of it."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()
    assert all(root.isExpanded() for root in _roots(view._tree).values())


def test_a_folder_holding_both_shapes_is_drawn_on_both_sides(qtbot, tmp_path):
    """A media root gathers whatever settings sit under it, so it can hold both —
    and each side draws the half that is its own."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    drawn = view._tree_view.keys_for_folder("image")  # the Images media root
    assert drawn == [oriented_key("image", "portrait"),
                     oriented_key("image", "landscape")]
    for key, expected in zip(drawn, (["t1"], ["w1"])):
        assert [row["prompt_id"] for row in view._rows_at(key)] == expected
        assert view._group_for_key(key).key == "image"  # its identity is unsplit


def test_a_slideshow_goes_to_the_region_its_side_names(qtbot, tmp_path):
    """The payoff: which screen a show is for is read off the key it was started
    from, not voted on by measuring the items back out."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    opened = []
    stub = SimpleNamespace(_playlist=SimpleNamespace(order=[]))

    def record(items, **kwargs):
        opened.append(kwargs)
        return stub

    view._open_slideshow = record
    view._tree.setCurrentItem(view._item_by_key[oriented_key(RECENTS_KEY, "portrait")])
    view._start_slideshow()

    assert opened and opened[0]["side"] == "portrait"
    assert opened[0]["location"] == oriented_key(RECENTS_KEY, "portrait")


def test_a_regions_base_state_is_its_side_of_the_library(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    for side, expected in (("portrait", ["t1"]), ("landscape", ["w1"])):
        key = view.region_base_location(side)
        assert key in view._item_by_key  # a real row, not a synthetic narrowing
        assert [row["prompt_id"] for row in view._rows_at(key)] == expected
