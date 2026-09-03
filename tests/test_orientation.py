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
from PyQt6.QtWidgets import QFrame, QLabel, QSplitter

from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY, RECENTS_KEY, REQUESTS_KEY, STARRED_KEY, TRASH_KEY, TRASH_LABEL,
)
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.orientation import (
    ORIENTATION_LABELS, base_of, filter_rows, orientation_of, oriented_key,
    row_orientation, split_key, split_rows,
)

from tests.test_gallery_view import FakeDB, _image, _row, _side_rows
from tests.test_icons import _ink_bounds  # the mark is measured the way the icons' own tests measure one


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


def test_a_video_being_made_from_a_picture_goes_by_that_pictures_shape(tmp_path):
    # An i2v asks for no size — it keeps its start frame's aspect at a fixed
    # pixel budget in-graph — so the frame is the only thing saying which way
    # the video will come out. Without it a running portrait video sat on the
    # Landscape side's Latest shelf and jumped sides the moment it landed.
    frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(frame)  # a tall start frame, named absolutely
    cooking = _row("v1", "wan22_i2v",
                   {"positive_prompt": "scene four", "input_image": str(frame)},
                   "wan22_i2v_v1.mp4", status="running", output_files="[]")
    assert row_orientation(cooking) == "portrait"


def test_a_size_asked_for_outranks_the_start_frame(tmp_path):
    # Unlocking the Dimensions field pins the output's shape whatever the frame's.
    frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(frame)
    cooking = _row("v2", "wan22_i2v",
                   {"positive_prompt": "scene five", "input_image": str(frame),
                    "width": 1280, "height": 720},
                   "wan22_i2v_v2.mp4", status="running", output_files="[]")
    assert row_orientation(cooking) == "landscape"


def test_an_unreadable_shape_files_under_landscape():
    # The same default the region routing uses for an unmeasurable set.
    bare = _image("b1", "scene three", 50, 3)  # no thumbnail, no file, no size
    assert row_orientation(bare) == "landscape"


def _rows(tree, orientation) -> list[str]:
    """The top-level rows of one half of the pane."""
    half = tree.tree_for(orientation)
    return [half.topLevelItem(i).text(0) for i in range(half.topLevelItemCount())]


def test_the_pane_is_one_table_of_contents_per_shape(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    # Each half carries the whole table of contents, not a slice of it.
    for orientation in ("portrait", "landscape"):
        assert _rows(view._tree, orientation) == [
            "Latest", "Favorites", "Experiments", "Requests", "Trash", "All",
        ]


def test_each_half_is_labelled_where_the_label_cannot_scroll_away(qtbot, tmp_path):
    """The whole point of two panes: which library you are reading is on screen
    however far down its own rows you have scrolled."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    assert [_heading_name(half).text() for half in _halves(view)] == [
        ORIENTATION_LABELS["portrait"], ORIENTATION_LABELS["landscape"]]
    # And the label belongs to the pane, not to the scrolling list under it.
    for orientation in ("portrait", "landscape"):
        assert view._tree.tree_for(orientation).findChildren(QLabel) == []


def test_each_heading_is_led_by_a_frame_of_its_own_shape(qtbot, tmp_path):
    """Which library a heading names is a shape, and a shape reads faster drawn
    than spelled: an upright mark over Portrait, a lying-down one over
    Landscape, each the transpose of the other so the pair reads at a glance."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    marks = [_heading_mark(half).pixmap() for half in _halves(view)]
    assert [mark.isNull() for mark in marks] == [False, False]
    portrait, landscape = (_ink_bounds(mark) for mark in marks)
    assert portrait[1] > portrait[0]          # the upright one is taller than wide
    assert landscape[0] > landscape[1]        # and the other is its quarter turn
    assert portrait == landscape[::-1]


def test_a_heading_describes_its_whole_side_wherever_the_cursor_lands(qtbot, tmp_path):
    """The mark and the word are two labels in one heading, so the description
    hangs off the heading rather than off whichever half the cursor found."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    for half, orientation in zip(_halves(view), ("portrait", "landscape")):
        heading = _heading(half)
        assert orientation in heading.toolTip()
        # Neither child claims one of its own, which is what lets the frame's
        # reach the cursor over either of them.
        assert [child.toolTip() for child in heading.findChildren(QLabel)] == ["", ""]


def _halves(view):
    splitter = view._tree.findChild(QSplitter)
    return [splitter.widget(i) for i in range(splitter.count())]


def _heading(half) -> QFrame:
    return next(child for child in half.findChildren(QFrame)
                if child.objectName() == "treeSectionLabel")


def _heading_mark(half) -> QLabel:
    return _heading(half).findChild(QLabel, "treeSectionMark")


def _heading_name(half) -> QLabel:
    return _heading(half).findChild(QLabel, "treeSectionName")


def test_both_halves_are_drawn_even_for_a_shape_with_nothing_in_it(qtbot, tmp_path):
    """The split is what tells a slideshow which screen it is for, so the side
    you have not generated for yet is still somewhere you can stand."""
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([wide]))
    qtbot.addWidget(view)
    view.refresh()

    # No folders of that shape yet, so no Favorites and no library — but the
    # shelves a first generation would land on are all there.
    assert _rows(view._tree, "portrait") == ["Experiments", "Requests", "Trash"]
    assert "All" in _rows(view._tree, "landscape")


def test_picking_in_one_half_lets_the_other_go(qtbot, tmp_path):
    """Only one folder is ever open, so a set picked across both halves — which
    is how a mixed-shape grouping would be composed — cannot be expressed."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    portrait_all = view._item_by_key[oriented_key("__all__", "portrait")]
    landscape_all = view._item_by_key[oriented_key("__all__", "landscape")]
    view._tree.setCurrentItem(portrait_all)
    assert view._selected_folder_key() == oriented_key("__all__", "portrait")

    view._tree.setCurrentItem(landscape_all)

    assert view._selected_folder_key() == oriented_key("__all__", "landscape")
    assert view._tree.selected_folder_keys() == [oriented_key("__all__", "landscape")]
    assert view._tree.tree_for("portrait").selectedItems() == []


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
    assert f"{TRASH_LABEL} (1)" in _rows(view._tree, "portrait")
    assert f"{TRASH_LABEL} (1)" in _rows(view._tree, "landscape")

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

    assert "Experiments (1)" in _rows(view._tree, "portrait")
    assert "Experiments (2)" in _rows(view._tree, "landscape")


def test_each_half_scrolls_on_its_own(qtbot, tmp_path):
    """Reaching a folder deep in one library must not scroll the other away."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    bars = [view._tree.tree_for(o).verticalScrollBar() for o in ("portrait", "landscape")]
    assert bars[0] is not bars[1]


def test_a_folder_holding_both_shapes_is_drawn_on_both_sides(qtbot, tmp_path):
    """A workflow folder gathers whatever settings sit under it, so it can hold
    both — and each side draws the half that is its own."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    drawn = view._tree_view.keys_for_folder("image/sdxl_t2i")  # the workflow folder
    assert drawn == [oriented_key("image/sdxl_t2i", "portrait"),
                     oriented_key("image/sdxl_t2i", "landscape")]
    for key, expected in zip(drawn, (["t1"], ["w1"])):
        assert [row["prompt_id"] for row in view._rows_at(key)] == expected
        assert view._group_for_key(key).key == "image/sdxl_t2i"  # its identity is unsplit


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
