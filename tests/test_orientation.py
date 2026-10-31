"""Two copies of the whole tree of contents, one per shape.

A mixed-shape set has no one screen to play on, so the tree is rooted on a
Portrait row and a Landscape row and each carries the ENTIRE tree of contents
over its own shape's rows: the collections, the folders the user composed, and the
All row over the library.  Standing anywhere is standing on one shape, so a
slideshow started there has exactly one region to go to — and which one is read
off the key rather than measured back out of the items.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QApplication, QFrame, QLabel
from shared_ui.colors import BORDER_SUBTLE

from origenerator import gallery
from origenerator import orientation as orientation_module
from origenerator.gallery.collection import (
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    TRASH_KEY,
    TRASH_LABEL,
)
from origenerator.gallery.sides import (
    BOTH,
    LANDSCAPE,
    PORTRAIT,
    SIDE_LABELS,
    SIDES,
    TOGETHER,
    side_covers,
    side_holds,
)
from origenerator.gui.gallery_tree import GROUP_ROLE
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.gui.stylesheet import CHOSEN, build_stylesheet
from origenerator.orientation import (
    base_of,
    filter_rows,
    oriented_key,
    row_orientation,
    side_of,
    split_key,
)
from tests.test_folder_tree import _shown
from tests.test_gallery_view import FakeDB, _image, _row, _side_rows
from tests.test_icons import (
    _ink_bounds,  # the mark is measured the way the icons' own tests measure one
)


def _thumbed(row: dict, tmp_path: Path, width: int, height: int) -> dict:
    thumb = tmp_path / f"{row['prompt_id']}_thumb.png"
    Image.new("RGB", (width, height)).save(thumb)
    row["thumbnail_path"] = str(thumb)
    return row


def _shaped(row: dict, tmp_path: Path, width: int, height: int) -> dict:
    """An image of this shape in a folder whose size says the same."""
    params = gallery.parse_params(row["params_json"])
    row["params_json"] = json.dumps({**params, "width": width, "height": height})
    return _thumbed(row, tmp_path, width, height)


def test_keys_split_and_join():
    assert oriented_key(RECENTS_KEY, "portrait") == "__recents__::portrait"
    assert split_key("__recents__::portrait") == (RECENTS_KEY, "portrait")
    assert split_key(RECENTS_KEY) == (RECENTS_KEY, None)
    assert split_key(None) == (None, None)
    assert split_key("__recents__::sideways") == ("__recents__::sideways", None)
    assert base_of("image/sdxl_t2i/m0011::portrait") == "image/sdxl_t2i/m0011"
    assert side_of("image/sdxl_t2i/m0011::portrait") == "portrait"


def test_rows_are_dealt_to_the_side_their_folders_shape_names(tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    assert row_orientation(tall) == "portrait"
    assert row_orientation(wide) == "landscape"
    assert filter_rows([tall, wide], "portrait") == [tall]
    assert filter_rows([tall, wide], "landscape") == [wide]
    assert filter_rows([tall, wide], None) == [tall, wide]


def test_an_image_goes_to_the_side_its_folder_names_whatever_its_own_shape(tmp_path):
    # The side is the folder's, read off the size its configuration states, so
    # every image in one folder sits on one side -- and an image that
    # disagrees with its folder shows up there rather than hiding on the other.
    wide = _row("w1", "sdxl_t2i",
                {"positive_prompt": "scene one", "width": 720, "height": 1280},
                "sdxl_t2i_w1.png")
    _thumbed(wide, tmp_path, 160, 90)
    assert row_orientation(wide) == "portrait"


def test_a_generation_with_no_image_yet_goes_by_the_size_it_asked_for():
    """Its folder joins the tree the moment it starts running, and it has to
    join on the side the image will land on rather than move there later."""
    in_flight = _row("c1", "sdxl_t2i",
                   {"positive_prompt": "scene three", "width": 720, "height": 1280},
                   "sdxl_t2i_c1.png")  # nothing on disk yet, so only the size answers
    assert row_orientation(in_flight) == "portrait"


def test_a_video_being_made_from_an_image_goes_by_that_images_shape(tmp_path):
    # An i2v asks for no size — it keeps its start frame's aspect at a fixed
    # pixel budget in-graph — so the frame is the only thing saying which way
    # the video will come out. Without it a running portrait video sat on the
    # Landscape side's Latest collection and jumped sides the moment it landed.
    frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(frame)  # a tall start frame, named absolutely
    in_flight = _row("v1", "wan22_i2v",
                   {"positive_prompt": "scene four", "input_image": str(frame)},
                   "wan22_i2v_v1.mp4", status="running", output_files="[]")
    assert row_orientation(in_flight) == "portrait"


def test_a_video_goes_by_its_folders_start_frame_whatever_size_its_row_stored(tmp_path):
    # A video folder is keyed by its start frame and not by a size its row
    # carries -- which on the early video workflow was stored and then never
    # used, the graph deriving the size from the frame all the same.
    frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(frame)
    video = _row("v2", "wan22_i2v",
                 {"positive_prompt": "scene five", "input_image": str(frame),
                  "width": 720, "height": 544},
                 "wan22_i2v_v2.mp4")
    assert row_orientation(video) == "portrait"


def test_an_unreadable_shape_files_under_landscape():
    # The same default the region routing uses for an unmeasurable set.
    bare = _image("b1", "scene three", 50, 3)  # no thumbnail, no file, no size
    assert row_orientation(bare) == "landscape"


def _start_frame(tmp_path: Path, name: str, width: int, height: int) -> Path:
    """An image on disk for a run to be conditioned on, named as an image row's
    own output is — which is how a start frame resolves back to its generation."""
    path = tmp_path / name
    Image.new("RGB", (width, height)).save(path)
    return path


def _video_in_flight(prompt_id: str, frame: Path, **params) -> dict:
    """A wan22_i2v row still in flight: queued, with no file of its own yet."""
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": "scene four", "seed": 4,
                 "input_image": str(frame), **params},
                f"wan22_i2v_{prompt_id}.mp4",
                status="pending", output_files="[]")


def test_a_queued_rows_click_opens_its_folder_across_the_split(qtbot, tmp_path):
    """A folder's key names the image the run animates, and that image can be
    on the other side — here a tall image in a folder whose size says
    landscape, so the image sits under Landscape while the video made from its
    tall frame sits under Portrait. Each side draws its own tree, but from the
    whole library's start frames: keyed off its own side's images alone, the
    Portrait tree would draw this folder under a name nothing else in the app
    computes, and the click on its queue row would find no row and do nothing."""
    frame = _start_frame(tmp_path, "sdxl_t2i_p3.png", 90, 160)
    image = _thumbed(
        _row("p3", "sdxl_t2i",
             {"positive_prompt": "scene three", "steps": 50, "seed": 3,
              "width": 1280, "height": 720},
             "sdxl_t2i_p3.png"),
        tmp_path, 90, 160)
    in_flight = _video_in_flight("v3", frame)

    view = GalleryView(FakeDB([image, in_flight]))
    qtbot.addWidget(view)
    view.refresh()
    view._update_queue()

    folder = gallery.settings_folder_key(
        in_flight, gallery.build_image_config_index([image]))
    (row,) = view._queue.rows()
    qtbot.mouseDClick(row, Qt.MouseButton.LeftButton)
    assert view.selected_folder_key() == oriented_key(folder, "portrait")


def _rows(pane, side) -> list[str]:
    """The top-level rows of one section of the pane."""
    tree = pane._trees[side]
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def _under_all(pane, side) -> list[str]:
    all_row = pane._trees[side].topLevelItem(0)
    return [all_row.child(i).text(0) for i in range(all_row.childCount())]


def test_the_pane_is_one_table_of_contents_per_shape(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    # Each half carries the whole tree of contents, not a slice of it.
    for side in ("portrait", "landscape"):
        assert _rows(view._tree, side) == ["All"]
        assert _under_all(view._tree, side)[:5] == [
            "Latest", "Favorites", "Enhanced", "Experiments", "Trash",
        ]


def test_the_pane_puts_both_shapes_in_one_list_when_asked(qtbot, tmp_path):
    """The two marks over the list are its radio: a list per shape, or one list
    of everything — which is what a slideshow mixing the shapes is started
    from."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()
    assert view._tree.sides == ("portrait", "landscape")

    view._tree.together_button.click()

    assert view._tree.sides == (BOTH,)
    assert _rows(view._tree, BOTH) == ["All"]
    assert _side_rows(view, BOTH) == ["t1", "w1"]


def _in_flight(prompt_id: str, width: int, height: int, status: str, seed: int = 1) -> dict:
    """An image still being made: no file yet, so its shape is the size it asked for."""
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": "scene six", "steps": 50, "seed": seed,
                 "width": width, "height": height},
                f"sdxl_t2i_{prompt_id}.png", status=status, output_files="[]")


_RUNS = {"tall": PORTRAIT, "wide": LANDSCAPE}


def _view_of_runs(qtbot):
    view = GalleryView(FakeDB([_in_flight("tall", 720, 1280, "pending"),
                               _in_flight("wide", 1280, 720, "running")]))
    qtbot.addWidget(view)
    view.refresh()
    return view


def _drawing(view, side: str) -> None:
    """The list on whichever of its arrangements draws *side*."""
    (view._tree.together_button if side == BOTH else view._tree.separate_button).click()


@pytest.mark.parametrize("side", SIDES)
def test_every_sides_latest_leads_with_the_runs_in_flight_it_holds(qtbot, side):
    """Queued or running, a run's card is on the Latest of each side that holds
    its shape. Together's Latest once showed none at all: its cards were picked
    by matching each run's shape against the side, which Both never matches."""
    view = _view_of_runs(qtbot)
    _drawing(view, side)

    view._tree.setCurrentItem(view._item_by_key[oriented_key(RECENTS_KEY, side)])

    assert set(view._browser._inflight_cards) == {
        run for run, shape in _RUNS.items() if side_holds(side, shape)}


@pytest.mark.parametrize("opened_first", SIDES)
def test_a_folder_shows_its_waiting_runs_whichever_latest_was_opened_before_it(
        qtbot, tmp_path, opened_first):
    """A folder's cards are the runs waiting in it. They were picked by the side
    of the Latest opened last, so after Together's Latest no folder showed any,
    and after Landscape's no portrait folder did."""
    finished = _shaped(_image("t1", "scene six", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([
        finished,
        _in_flight("t2", 90, 160, "pending", seed=2),
        _in_flight("t3", 90, 160, "pending", seed=3),
        _shaped(_image("w1", "scene seven", 50, 4), tmp_path, 160, 90),
    ]))
    qtbot.addWidget(view)
    view.refresh()
    _drawing(view, opened_first)
    view._tree.setCurrentItem(view._item_by_key[oriented_key(RECENTS_KEY, opened_first)])
    holding_the_folder = next(side for side in view._tree.sides
                              if side_holds(side, PORTRAIT))
    folder = gallery.settings_folder_key(finished, gallery.build_image_config_index([finished]))

    view._tree.setCurrentItem(view._item_by_key[oriented_key(folder, holding_the_folder)])

    assert set(view._browser._inflight_cards) == {"t2", "t3"}


@pytest.mark.parametrize("side", SIDES)
def test_a_folder_composed_on_one_side_is_drawn_on_each_side_covering_it(
        qtbot, tmp_path, side):
    db = FakeDB([_shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)])
    db.create_custom_folder("Keepers", side=PORTRAIT)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    _drawing(view, side)

    assert ("Keepers" in _rows(view._tree, side)) == side_covers(side, PORTRAIT)


def test_a_rows_shape_is_worked_out_once_however_often_it_is_asked():
    """One click on the folder list asks thousands of rows for their shape
    several times over, so the answer is kept against the stored fields it is
    read from rather than worked out per ask."""
    orientation_module._asked_shape.cache_clear()
    row = {"workflow_name": "sdxl_t2i",
           "params_json": '{"width": 101, "height": 202}'}

    assert row_orientation(row) == "portrait"
    assert row_orientation(dict(row)) == "portrait"

    assert orientation_module._asked_shape.cache_info().misses == 1


def _counting_builds(monkeypatch):
    built = []
    real = gallery.build_gallery_tree
    monkeypatch.setattr(gallery, "build_gallery_tree",
                        lambda *args, **kwargs: built.append(1) or real(*args, **kwargs))
    return built


def test_the_radio_builds_no_list_it_has_already_built(qtbot, tmp_path, monkeypatch):
    """Each shape's list, and the list of both shapes, costs a pass over the
    whole library. The radio moves between lists the gallery has already built,
    and every click used to build all three again from nothing. The list of
    both shapes is built the first time Both is drawn, never before and never
    again: a landing redraws Separate far more often than the radio moves."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()
    built = _counting_builds(monkeypatch)

    view._tree.together_button.click()
    view._tree.separate_button.click()
    view._tree.together_button.click()

    assert built == [1]


def test_a_library_that_has_changed_builds_its_lists_again(qtbot, tmp_path, monkeypatch):
    """What the lists are kept against: the rows and the folder names they were
    built from. A generation landing is a different library."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    db = FakeDB([tall])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    built = _counting_builds(monkeypatch)

    db._rows.append(_thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90))
    view.refresh()

    assert built


def _word_beside(button):
    return button.parent().findChild(QLabel).text()


def test_the_radio_over_the_list_wears_each_word_beside_its_button(qtbot, tmp_path):
    """Two marks alone left him reading the shapes to work out which was which,
    so each has its word to the side of it -- on the button the pair of them
    took two rows of the narrowest column -- and the one in force wears the
    blue of any other selection."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    assert _word_beside(view._tree.separate_button) == "Separate"
    assert _word_beside(view._tree.together_button) == "Together"
    assert view._tree.separate_button.isChecked()
    assert not view._tree.together_button.isChecked()
    for button in (view._tree.separate_button, view._tree.together_button):
        assert button.text() == ""
        assert button.property(CHOSEN) is True
        assert not button.icon().isNull()


def _choice_rows(tree):
    buttons = (tree.separate_button, tree.together_button)
    for button in buttons:
        word = button.parent().findChild(QLabel)
        assert button.width() == button.height()
        assert word.width() >= word.sizeHint().width()
    return {button.mapTo(tree, QPoint()).y() for button in buttons}


def _laid_out(qtbot, width):
    tree = SplitFolderTree(GROUP_ROLE)
    qtbot.addWidget(tree)
    tree.resize(width, 600)
    tree.show()
    tree.layout().activate()
    return tree


def test_the_two_choices_and_their_words_share_one_row(qtbot):
    """Both choices on one row, each a square mark with every letter of its
    word beside it, wherever the column is wide enough to hold them."""
    assert len(_choice_rows(_laid_out(qtbot, 400))) == 1


def test_a_column_too_narrow_for_both_choices_gives_each_its_own_row(qtbot):
    """Squeezed, a word is never clipped down to a stub: the second choice
    drops to a row of its own instead."""
    assert len(_choice_rows(_laid_out(qtbot, 120))) == 2


def test_clicking_a_choice_s_word_picks_it(qtbot, tmp_path):
    """The word is as much the control as the mark is, the way the word beside
    any other radio in the app is."""
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    word = view._tree.together_button.parent().findChild(QLabel)
    qtbot.mouseClick(word, Qt.MouseButton.LeftButton)

    assert view._tree.together_button.isChecked()
    assert view._tree.sides == (BOTH,)


def test_a_folder_open_on_together_is_open_again_after_a_turn_on_separate(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.together_button.click()
    folder = oriented_key("image/sdxl_t2i", BOTH)
    view._tree_item_for(folder).setExpanded(True)

    view._tree.separate_button.click()
    view._tree.together_button.click()

    assert view._tree_item_for(folder).isExpanded()


def test_each_half_is_labelled_where_the_label_cannot_scroll_away(qtbot, tmp_path):
    """The whole point of two panes: which library you are reading is on screen
    however far down its own rows you have scrolled."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    assert [_heading_name(section).text() for section in _sections(view)] == [
        SIDE_LABELS["portrait"], SIDE_LABELS["landscape"]]
    # And the label belongs to the pane, not to the scrolling list under it.
    for side in ("portrait", "landscape"):
        assert view._tree._trees[side].findChildren(QLabel) == []


def test_each_heading_is_led_by_a_frame_of_its_own_shape(qtbot, tmp_path):
    """Which library a heading names is a shape, and a shape reads faster drawn
    than spelled: an upright mark over Portrait, a lying-down one over
    Landscape, each the transpose of the other so the pair reads at a glance."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    marks = [_heading_mark(section).pixmap() for section in _sections(view)]
    assert [mark.isNull() for mark in marks] == [False, False]
    portrait, landscape = (_ink_bounds(mark) for mark in marks)
    assert portrait[1] > portrait[0]          # the upright one is taller than wide
    assert landscape[0] > landscape[1]        # and the other is its quarter turn
    assert portrait == landscape[::-1]


def test_a_heading_describes_its_whole_side_wherever_the_cursor_lands(qtbot, tmp_path):
    """The mark and the word are two labels in one heading, so the description
    hangs off the heading rather than off whichever half the cursor found."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    for section, side in zip(_sections(view), ("portrait", "landscape")):
        heading = _heading(section)
        assert side in heading.toolTip()
        # Neither child claims one of its own, which is what lets the frame's
        # reach the cursor over either of them.
        assert [child.toolTip() for child in heading.findChildren(QLabel)] == ["", ""]


def test_together_s_one_list_wears_no_heading_since_the_choice_over_it_names_it(
        qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.together_button.click()

    (section,) = _sections(view)
    assert _headings(section) == []


def test_together_s_list_is_ruled_off_above_as_each_of_separate_s_lists_is(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        pane = _laid_out(qtbot, 300)
        separate = [_rows_from_the_lighter_line_to_the_list(pane, side)
                    for side in pane.sides]
        pane.choose_sides(TOGETHER)
        app.processEvents()
        pane.layout().activate()
        together = [_rows_from_the_lighter_line_to_the_list(pane, side)
                    for side in pane.sides]
    finally:
        app.setStyleSheet(prior)

    assert None not in separate and len(set(separate)) == 1
    assert together == separate[:1]


def test_together_s_line_sits_as_far_under_its_choices_as_portrait_s_under_its_word(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        pane = _laid_out(qtbot, 300)
        under_the_word = _clear_rows_over_the_line(
            pane, PORTRAIT, _heading_name(pane._sections[PORTRAIT]))
        pane.choose_sides(TOGETHER)
        app.processEvents()
        pane.layout().activate()
        under_the_choices = _clear_rows_over_the_line(pane, BOTH, pane._choices)
    finally:
        app.setStyleSheet(prior)

    assert under_the_choices == under_the_word


def _clear_rows_over_the_line(pane, side, above) -> int:
    image = pane.grab().toImage()
    (rule,) = pane._sections[side].findChildren(QFrame, "treeSectionRule")
    line = rule.mapTo(pane, QPoint()).y()
    ground = image.pixelColor(pane.width() - 2, line - 1)
    box = QRect(above.mapTo(pane, QPoint()), above.size())
    ink = next(row for row in range(box.bottom(), box.top() - 1, -1)
               if any(image.pixelColor(x, row) != ground
                      for x in range(box.left(), box.right() + 1)))
    return line - ink - 1


def _rows_from_the_lighter_line_to_the_list(pane, side) -> int | None:
    section, tree = pane._sections[side], pane._trees[side]
    image = section.grab().toImage()
    top = tree.mapTo(section, QPoint()).y()
    across = section.width() // 2
    return next((top - row for row in range(top - 1, -1, -1)
                 if image.pixelColor(across, row) == BORDER_SUBTLE), None)


def _sections(view):
    """The sections the pane is drawing, in the order it draws them."""
    return [view._tree._sections[side] for side in view._tree.sides]


def _headings(section) -> list[QFrame]:
    return [child for child in section.findChildren(QFrame)
            if child.objectName() == "treeSectionLabel"]


def _heading(section) -> QFrame:
    (heading,) = _headings(section)
    return heading


def _heading_mark(section) -> QLabel:
    return _heading(section).findChild(QLabel, "treeSectionMark")


def _heading_name(section) -> QLabel:
    return _heading(section).findChild(QLabel, "treeSectionName")


def test_both_shapes_are_drawn_even_for_one_with_nothing_in_it(qtbot, tmp_path):
    """The split is what tells a slideshow which screen it is for, so the side
    you have not generated for yet is still somewhere you can stand."""
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([wide]))
    qtbot.addWidget(view)
    view.refresh()

    # No folders of that shape yet, so no Favorites and no library — but the
    # collections a first generation would land on are all there.
    assert _rows(view._tree, "portrait") == ["All"]
    assert _under_all(view._tree, "portrait") == ["Experiments", "Trash"]
    assert "Favorites" in _under_all(view._tree, "landscape")


def test_picking_in_one_half_lets_the_other_go(qtbot, tmp_path):
    """Only one folder is ever open, so a set picked across both halves — which
    is how a mixed-shape grouping would be composed — cannot be expressed."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    portrait_all = view._item_by_key[oriented_key("__all__", "portrait")]
    landscape_all = view._item_by_key[oriented_key("__all__", "landscape")]
    view._tree.setCurrentItem(portrait_all)
    assert view.selected_folder_key() == oriented_key("__all__", "portrait")

    view._tree.setCurrentItem(landscape_all)

    assert view.selected_folder_key() == oriented_key("__all__", "landscape")
    assert view._tree.selected_folder_keys() == [oriented_key("__all__", "landscape")]
    assert view._tree._trees["portrait"].selectedItems() == []


def test_each_side_holds_only_its_own_shape(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    assert _side_rows(view, "portrait") == ["t1"]
    assert _side_rows(view, "landscape") == ["w1"]


def test_a_collection_belongs_to_one_side(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._item_by_key[oriented_key(RECENTS_KEY, "portrait")])

    assert view._browser.listed_prompt_ids() == ["t1"]
    # The slideshow plays exactly the listing — a homogeneous set, so the
    # hosting session routes the whole slideshow to the portrait region.
    assert [row["prompt_id"] for row in view.rows_to_play()] == ["t1"]
    # And it is what history remembers, so Back returns to that side's collection.
    assert view._current_collection_key() == oriented_key(RECENTS_KEY, "portrait")


def test_favorites_collects_the_bookmarks_of_its_own_side(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    db = FakeDB([tall, wide])
    db.set_generation_favorite("t1", True)
    db.set_generation_favorite("w1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._item_by_key[oriented_key(FAVORITES_KEY, "landscape")])

    assert view._browser.listed_prompt_ids() == ["w1"]
    assert [row["prompt_id"] for row in view.rows_to_play()] == ["w1"]


def test_the_trash_collection_splits_too(qtbot, tmp_path):
    """The half-measure this replaces left Trash and All whole; the whole table
    of contents means the whole of it."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    view._actions.delete_rows([tall, wide])
    view.refresh()

    assert sorted(held["prompt_id"] for held in view._held_rows) == ["t1", "w1"]
    for side in ("portrait", "landscape"):
        assert _shown(view._item_by_key[oriented_key(TRASH_KEY, side)]) == f"(1) {TRASH_LABEL}"

    view._tree.setCurrentItem(view._item_by_key[oriented_key(TRASH_KEY, "portrait")])
    assert view._current_collection_key() == oriented_key(TRASH_KEY, "portrait")
    assert [row["prompt_id"] for row in view.rows_to_play()] == ["t1"]


def test_a_side_counts_only_its_own_waiting_work(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    tall["source"] = "experiment"
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    wide["source"] = "experiment"
    other = _shaped(_image("w2", "scene four", 50, 3), tmp_path, 160, 90)
    other["source"] = "experiment"
    view = GalleryView(FakeDB([tall, wide, other]))
    qtbot.addWidget(view)
    view.refresh()

    assert _shown(view._item_by_key[oriented_key(EXPERIMENTS_KEY, "portrait")]) == "(1) Experiments"
    assert _shown(view._item_by_key[oriented_key(EXPERIMENTS_KEY, "landscape")]) == "(2) Experiments"


def test_each_half_scrolls_on_its_own(qtbot, tmp_path):
    """Reaching a folder deep in one library must not scroll the other away."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    bars = [view._tree._trees[o].verticalScrollBar() for o in ("portrait", "landscape")]
    assert bars[0] is not bars[1]


def test_a_folder_holding_both_shapes_is_drawn_on_both_sides(qtbot, tmp_path):
    """A workflow folder gathers whatever settings sit under it, so it can hold
    both — and each side draws the half that is its own."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    drawn = view._tree_view.keys_for_folder("image/sdxl_t2i")  # the workflow folder
    assert drawn == [oriented_key("image/sdxl_t2i", "portrait"),
                     oriented_key("image/sdxl_t2i", "landscape")]
    for key, expected in zip(drawn, (["t1"], ["w1"])):
        assert [row["prompt_id"] for row in view._slideshows.rows_at(key)] == expected
        assert view.group_for_key(key).key == "image/sdxl_t2i"  # its identity is unsplit


def test_a_slideshow_goes_to_the_region_its_side_names(qtbot, tmp_path):
    """The payoff: which screen a slideshow is for is read off the key it was started
    from, not voted on by measuring the items back out."""
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    opened = []
    stub = SimpleNamespace(_playlist=SimpleNamespace(order=[]))

    def record(items, **kwargs):
        opened.append(kwargs)
        return stub

    view._slideshows.open = record
    view._tree.setCurrentItem(view._item_by_key[oriented_key(RECENTS_KEY, "portrait")])
    view._slideshows.start()

    assert opened and opened[0]["side"] == "portrait"
    assert opened[0]["location"] == oriented_key(RECENTS_KEY, "portrait")


def test_a_regions_base_state_is_its_side_of_the_library(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    for side, expected in (("portrait", ["t1"]), ("landscape", ["w1"])):
        key = view._slideshows.base_location(side)
        assert key in view._item_by_key  # a real row, not a synthetic narrowing
        assert [row["prompt_id"] for row in view._slideshows.rows_at(key)] == expected
