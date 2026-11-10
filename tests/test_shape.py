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
from origenerator.gallery.collection import (
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
    TRASH_LABEL,
)
from origenerator.gallery.shapes import (
    BOTH,
    LANDSCAPE,
    PORTRAIT,
    SHAPE_LABELS,
    SHAPES_AND_BOTH,
    TOGETHER,
    shape_covers,
    shape_holds,
)
from origenerator.gui.gallery_tree import GROUP_ROLE
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.gui.stylesheet import CHOSEN, build_stylesheet
from origenerator.item_shape import (
    base_of,
    filter_rows,
    key_holds,
    row_shape,
    shape_of,
    shaped_key,
    split_key,
)
from tests.gallery_view_support import FakeDB, _image, _row, _shape_rows
from tests.test_folder_tree import _shown
from tests.test_icons import (
    _ink_bounds,
)


def _thumbed(row: dict, tmp_path: Path, width: int, height: int) -> dict:
    thumb = tmp_path / f"{row['prompt_id']}_thumb.png"
    Image.new("RGB", (width, height)).save(thumb)
    row["thumbnail_path"] = str(thumb)
    return row


def _shaped(row: dict, tmp_path: Path, width: int, height: int) -> dict:
    params = gallery.parse_params(row["params_json"])
    row["params_json"] = json.dumps({**params, "width": width, "height": height})
    return _thumbed(row, tmp_path, width, height)


def test_keys_split_and_join():
    assert shaped_key(LATEST_KEY, "portrait") == "__recents__::portrait"
    assert split_key("__recents__::portrait") == (LATEST_KEY, "portrait")
    assert split_key(LATEST_KEY) == (LATEST_KEY, None)
    assert split_key(None) == (None, None)
    assert split_key("__recents__::sideways") == ("__recents__::sideways", None)
    assert base_of("image/sdxl_t2i/m0011::portrait") == "image/sdxl_t2i/m0011"
    assert shape_of("image/sdxl_t2i/m0011::portrait") == "portrait"


def test_rows_are_dealt_to_the_side_their_folders_shape_names(tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    assert row_shape(tall) == "portrait"
    assert row_shape(wide) == "landscape"
    assert filter_rows([tall, wide], "portrait") == [tall]
    assert filter_rows([tall, wide], "landscape") == [wide]
    assert filter_rows([tall, wide], None) == [tall, wide]


def test_an_image_goes_to_the_side_its_folder_names_whatever_its_own_shape(tmp_path):
    wide = _row("w1", "sdxl_t2i",
                {"positive_prompt": "scene one", "width": 720, "height": 1280},
                "sdxl_t2i_w1.png")
    _thumbed(wide, tmp_path, 160, 90)
    assert row_shape(wide) == "portrait", \
        "an image that disagrees with its folder shows up there, not hidden on the other side"


def test_a_generation_with_no_image_yet_goes_by_the_size_it_asked_for():
    in_flight = _row("c1", "sdxl_t2i",
                   {"positive_prompt": "scene three", "width": 720, "height": 1280},
                   "sdxl_t2i_c1.png")
    assert row_shape(in_flight) == "portrait"


def test_a_video_being_made_from_an_image_goes_by_that_images_shape(tmp_path):
    absolute_frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(absolute_frame)
    in_flight = _row("v1", "wan22_i2v",
                   {"positive_prompt": "scene four", "input_image": str(absolute_frame)},
                   "wan22_i2v_v1.mp4", status="running", output_files="[]")
    assert row_shape(in_flight) == "portrait", (
        "by any other shape a running portrait video sat in Landscape's Latest "
        "and changed sides the moment it landed")


def test_a_video_goes_by_its_folders_start_frame_whatever_size_its_row_stored(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(frame)
    video = _row("v2", "wan22_i2v",
                 {"positive_prompt": "scene five", "input_image": str(frame),
                  "width": 720, "height": 544},
                 "wan22_i2v_v2.mp4")
    assert row_shape(video) == "portrait", \
        "the size an early video row stored was never the size its graph used"


def test_a_video_with_a_thumbnail_goes_by_its_thumbnail_before_its_start_frame(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (90, 160)).save(frame)
    video = _row("v3", "wan22_i2v",
                 {"positive_prompt": "scene six", "input_image": str(frame)},
                 "wan22_i2v_v3.mp4")
    _thumbed(video, tmp_path, 160, 90)

    assert row_shape(video) == "landscape"


def test_a_folder_holds_itself_and_the_folders_below_it_on_the_same_shape_only():
    folder = shaped_key("image/sdxl_t2i", "portrait")

    assert key_holds(folder, folder)
    assert key_holds(folder, shaped_key("image/sdxl_t2i/m0011", "portrait"))
    assert not key_holds(folder, shaped_key("image/sdxl_t2i/m0011", "landscape"))
    assert not key_holds(folder, shaped_key("image/sdxl_t2i_other", "portrait"))
    assert not key_holds(shaped_key("image/sdxl_t2i", "portrait"), "image/sdxl_t2i")


def test_an_unreadable_shape_files_under_landscape():
    bare = _image("b1", "scene three", 50, 3)
    assert row_shape(bare) == "landscape", \
        "the same default a slideshow's routing uses for a set it cannot measure"


def _start_frame(tmp_path: Path, output_name: str, width: int, height: int) -> Path:
    path = tmp_path / output_name
    Image.new("RGB", (width, height)).save(path)
    return path


def _video_in_flight(prompt_id: str, frame: Path, **params) -> dict:
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": "scene four", "seed": 4,
                 "input_image": str(frame), **params},
                f"wan22_i2v_{prompt_id}.mp4",
                status="pending", output_files="[]")


def test_a_queued_rows_click_opens_its_folder_across_the_split(qtbot, tmp_path):
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
    assert view.selected_folder_key() == shaped_key(folder, "portrait"), (
        "each shape's tree keys a video's folder from the whole library's start frames; "
        "from its own side's images alone the folder would get a key nothing else works out")


def _rows(pane, shape) -> list[str]:
    tree = pane._trees[shape]
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def _under_all(pane, shape) -> list[str]:
    all_row = pane._trees[shape].topLevelItem(0)
    return [all_row.child(i).text(0) for i in range(all_row.childCount())]


def test_the_pane_is_one_table_of_contents_per_shape(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    for shape in ("portrait", "landscape"):
        assert _rows(view._tree, shape) == ["All"], \
            "a set mixing the shapes has no one screen to play on, so each shape has the whole tree"
        assert _under_all(view._tree, shape)[:5] == [
            "Latest", "Favorites", "Enhanced", "Experiments", "Trash",
        ]


def test_the_pane_puts_both_shapes_in_one_list_when_asked(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()
    assert view._tree.shapes == ("portrait", "landscape")

    view._tree.together_button.click()

    assert view._tree.shapes == (BOTH,)
    assert _rows(view._tree, BOTH) == ["All"]
    assert _shape_rows(view, BOTH) == ["t1", "w1"]


def _in_flight(prompt_id: str, width: int, height: int, status: str, seed: int = 1) -> dict:
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


def _drawing(view, shape: str) -> None:
    (view._tree.together_button if shape == BOTH else view._tree.separate_button).click()


@pytest.mark.parametrize("shape", SHAPES_AND_BOTH)
def test_every_sides_latest_leads_with_the_runs_in_flight_it_holds(qtbot, shape):
    view = _view_of_runs(qtbot)
    _drawing(view, shape)

    view._tree.setCurrentItem(view._item_by_key[shaped_key(LATEST_KEY, shape)])

    assert set(view._gallery_pane._inflight_tiles) == {
        run for run, of_item in _RUNS.items() if shape_holds(shape, of_item)}


@pytest.mark.parametrize("opened_first", SHAPES_AND_BOTH)
def test_a_folder_shows_its_waiting_runs_whichever_latest_was_opened_before_it(
        qtbot, tmp_path, opened_first):
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
    view._tree.setCurrentItem(view._item_by_key[shaped_key(LATEST_KEY, opened_first)])
    holding_the_folder = next(shape for shape in view._tree.shapes
                              if shape_holds(shape, PORTRAIT))
    folder = gallery.settings_folder_key(finished, gallery.build_image_config_index([finished]))

    view._tree.setCurrentItem(view._item_by_key[shaped_key(folder, holding_the_folder)])

    assert set(view._gallery_pane._inflight_tiles) == {"t2", "t3"}


@pytest.mark.parametrize("shape", SHAPES_AND_BOTH)
def test_a_folder_composed_on_one_side_is_drawn_on_each_side_covering_it(
        qtbot, tmp_path, shape):
    db = FakeDB([_shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)])
    db.create_custom_collection("Keepers", shape=PORTRAIT)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    _drawing(view, shape)

    assert ("Keepers" in _rows(view._tree, shape)) == shape_covers(shape, PORTRAIT)


def _counting_builds(monkeypatch):
    built = []
    real = gallery.build_gallery_tree
    monkeypatch.setattr(gallery, "build_gallery_tree",
                        lambda *args, **kwargs: built.append(1) or real(*args, **kwargs))
    return built


def test_the_radio_builds_no_list_it_has_already_built(qtbot, tmp_path, monkeypatch):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _thumbed(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()
    built = _counting_builds(monkeypatch)

    view._tree.together_button.click()
    view._tree.separate_button.click()
    view._tree.together_button.click()

    assert built == [1], (
        "each list is a pass over the whole library, and a landing redraws Separate "
        "far more often than the radio moves, so Together's list is built when first drawn")


def test_a_library_that_has_changed_builds_its_lists_again(qtbot, tmp_path, monkeypatch):
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


def test_a_folder_given_a_name_builds_the_lists_again(qtbot, tmp_path, monkeypatch):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    db = FakeDB([tall])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    built = _counting_builds(monkeypatch)

    db.upsert_folder_meta(gallery.settings_folder_key(tall), custom_name="Tall ones",
                          favorite=False, level="settings", ref_prompt_id="t1")
    view.refresh()

    assert built


def test_the_radio_over_the_list_wears_each_word_beside_its_button(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    assert _word_beside(view._tree.separate_button) == "Separate", \
        "two marks alone left the user reading the shapes to work out which was which"
    assert _word_beside(view._tree.together_button) == "Together"
    assert view._tree.separate_button.isChecked()
    assert not view._tree.together_button.isChecked()
    for button in (view._tree.separate_button, view._tree.together_button):
        assert button.text() == "", \
            "on the buttons the two words took two rows of the narrowest column"
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
    assert len(_choice_rows(_laid_out(qtbot, 400))) == 1


def test_a_column_too_narrow_for_both_choices_gives_each_its_own_row(qtbot):
    assert len(_choice_rows(_laid_out(qtbot, 120))) == 2


def test_clicking_a_choice_s_word_picks_it(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    word = view._tree.together_button.parent().findChild(QLabel)
    qtbot.mouseClick(word, Qt.MouseButton.LeftButton)

    assert view._tree.together_button.isChecked()
    assert view._tree.shapes == (BOTH,)


def test_a_folder_open_on_together_is_open_again_after_a_turn_on_separate(qtbot, tmp_path):
    tall = _thumbed(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.together_button.click()
    folder = shaped_key("image/sdxl_t2i", BOTH)
    view._tree_item_for(folder).setExpanded(True)

    view._tree.separate_button.click()
    view._tree.together_button.click()

    assert view._tree_item_for(folder).isExpanded()


def test_each_half_is_labelled_where_the_label_cannot_scroll_away(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    assert [_heading_name(section).text() for section in _sections(view)] == [
        SHAPE_LABELS["portrait"], SHAPE_LABELS["landscape"]]
    for shape in ("portrait", "landscape"):
        assert view._tree._trees[shape].findChildren(QLabel) == []


def test_each_heading_is_led_by_a_frame_of_its_own_shape(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    marks = [_heading_mark(section).pixmap() for section in _sections(view)]
    assert [mark.isNull() for mark in marks] == [False, False], (
        "a shape reads faster drawn than spelled")
    portrait, landscape = (_ink_bounds(mark) for mark in marks)
    assert portrait[1] > portrait[0]
    assert landscape[0] > landscape[1]
    assert portrait == landscape[::-1]


def test_a_heading_describes_its_whole_side_wherever_the_cursor_lands(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    view = GalleryView(FakeDB([tall]))
    qtbot.addWidget(view)
    view.refresh()

    for section, shape in zip(_sections(view), ("portrait", "landscape"), strict=True):
        heading = _heading(section)
        assert shape in heading.toolTip()
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
        separate = [_rows_from_the_lighter_line_to_the_list(pane, shape)
                    for shape in pane.shapes]
        pane.choose_shapes(TOGETHER)
        app.processEvents()
        pane.layout().activate()
        together = [_rows_from_the_lighter_line_to_the_list(pane, shape)
                    for shape in pane.shapes]
    finally:
        app.setStyleSheet(prior)

    assert None not in separate
    assert len(set(separate)) == 1
    assert together == separate[:1]


def test_together_s_line_sits_as_far_under_its_choices_as_portrait_s_under_its_word(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        pane = _laid_out(qtbot, 300)
        under_the_word = _clear_rows_over_the_line(
            pane, PORTRAIT, _heading_name(pane._sections[PORTRAIT]))
        pane.choose_shapes(TOGETHER)
        app.processEvents()
        pane.layout().activate()
        under_the_choices = _clear_rows_over_the_line(pane, BOTH, pane._choices)
    finally:
        app.setStyleSheet(prior)

    assert under_the_choices == under_the_word


def _clear_rows_over_the_line(pane, shape, above) -> int:
    image = pane.grab().toImage()
    (rule,) = pane._sections[shape].findChildren(QFrame, "treeSectionRule")
    line = rule.mapTo(pane, QPoint()).y()
    ground = image.pixelColor(pane.width() - 2, line - 1)
    box = QRect(above.mapTo(pane, QPoint()), above.size())
    ink = next(row for row in range(box.bottom(), box.top() - 1, -1)
               if any(image.pixelColor(x, row) != ground
                      for x in range(box.left(), box.right() + 1)))
    return line - ink - 1


def _rows_from_the_lighter_line_to_the_list(pane, shape) -> int | None:
    section, tree = pane._sections[shape], pane._trees[shape]
    image = section.grab().toImage()
    top = tree.mapTo(section, QPoint()).y()
    across = section.width() // 2
    return next((top - row for row in range(top - 1, -1, -1)
                 if image.pixelColor(across, row) == BORDER_SUBTLE), None)


def _sections(view):
    return [view._tree._sections[shape] for shape in view._tree.shapes]


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
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([wide]))
    qtbot.addWidget(view)
    view.refresh()

    assert _rows(view._tree, "portrait") == ["All"], \
        ("the split is what tells a slideshow which screen it is for, so a shape nothing has "
         "been made for yet is still somewhere to stand and to start a slideshow from")
    assert _under_all(view._tree, "portrait") == ["Experiments", "Trash"], \
        "the collections a first generation of that shape would land in"
    assert "Favorites" in _under_all(view._tree, "landscape")


def test_picking_in_one_half_lets_the_other_go(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    portrait_all = view._item_by_key[shaped_key("__all__", "portrait")]
    landscape_all = view._item_by_key[shaped_key("__all__", "landscape")]
    view._tree.setCurrentItem(portrait_all)
    assert view.selected_folder_key() == shaped_key("__all__", "portrait")

    view._tree.setCurrentItem(landscape_all)

    assert view.selected_folder_key() == shaped_key("__all__", "landscape")
    assert view._tree.selected_folder_keys() == [shaped_key("__all__", "landscape")]
    assert view._tree._trees["portrait"].selectedItems() == []


def _view_with_a_row_on_each_side(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()
    return (view, view._item_by_key[shaped_key("__all__", "portrait")],
            view._item_by_key[shaped_key("__all__", "landscape")])


def test_the_half_that_lets_go_when_the_other_is_picked_reports_no_change_of_its_own(qtbot, tmp_path):
    view, portrait_all, landscape_all = _view_with_a_row_on_each_side(qtbot, tmp_path)
    view._tree.setCurrentItem(portrait_all)
    reported = []
    view._tree.currentItemChanged.connect(lambda current, _previous: reported.append(current))

    view._tree.setCurrentItem(landscape_all)

    assert reported
    assert None not in reported


def test_silencing_the_folder_list_silences_both_halves(qtbot, tmp_path):
    view, portrait_all, landscape_all = _view_with_a_row_on_each_side(qtbot, tmp_path)
    view._tree.setCurrentItem(portrait_all)
    reported = []
    view._tree._trees["landscape"].currentItemChanged.connect(
        lambda current, _previous: reported.append(current))

    view._tree.blockSignals(True)
    view._tree.setCurrentItem(landscape_all)
    view._tree.blockSignals(False)

    assert reported == []
    assert view._tree.is_current(landscape_all)


def test_each_side_holds_only_its_own_shape(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    assert _shape_rows(view, "portrait") == ["t1"]
    assert _shape_rows(view, "landscape") == ["w1"]


def test_a_collection_belongs_to_one_side(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._item_by_key[shaped_key(LATEST_KEY, "portrait")])

    assert view._gallery_pane.listed_prompt_ids() == ["t1"]
    assert [row["prompt_id"] for row in view.rows_to_play()] == ["t1"]
    assert view._current_collection_key() == shaped_key(LATEST_KEY, "portrait")


def test_favorites_collects_the_favorites_of_its_own_side(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    db = FakeDB([tall, wide])
    db.set_generation_favorite("t1", True)
    db.set_generation_favorite("w1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._item_by_key[shaped_key(FAVORITES_KEY, "landscape")])

    assert view._gallery_pane.listed_prompt_ids() == ["w1"]
    assert [row["prompt_id"] for row in view.rows_to_play()] == ["w1"]


def test_the_trash_collection_splits_too(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    view._edits.delete_rows([tall, wide])
    view.refresh()

    assert sorted(held["prompt_id"] for held in view._held_rows) == ["t1", "w1"]
    for shape in ("portrait", "landscape"):
        assert _shown(view._item_by_key[shaped_key(TRASH_KEY, shape)]) == f"(1) {TRASH_LABEL}"

    view._tree.setCurrentItem(view._item_by_key[shaped_key(TRASH_KEY, "portrait")])
    assert view._current_collection_key() == shaped_key(TRASH_KEY, "portrait")
    assert view.listed_prompt_ids() == ["t1"]


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

    assert _shown(view._item_by_key[shaped_key(EXPERIMENTS_KEY, "portrait")]) == "(1) Experiments"
    assert _shown(view._item_by_key[shaped_key(EXPERIMENTS_KEY, "landscape")]) == "(2) Experiments"


def test_each_half_scrolls_on_its_own(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    bars = [view._tree._trees[o].verticalScrollBar() for o in ("portrait", "landscape")]
    assert bars[0] is not bars[1]


def test_a_folder_holding_both_shapes_is_drawn_on_both_sides(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    drawn = view._tree_view.keys_for_folder("image/sdxl_t2i")
    assert drawn == [shaped_key("image/sdxl_t2i", "portrait"),
                     shaped_key("image/sdxl_t2i", "landscape")]
    for key, expected in zip(drawn, (["t1"], ["w1"]), strict=True):
        assert [row["prompt_id"] for row in view._slideshows.rows_at(key)] == expected
        assert view.group_for_key(key).key == "image/sdxl_t2i"


def test_a_slideshow_goes_to_the_region_its_side_names(qtbot, tmp_path):
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
    view._tree.setCurrentItem(view._item_by_key[shaped_key(LATEST_KEY, "portrait")])
    view._slideshows.start()

    assert opened
    assert opened[0]["shape"] == "portrait"
    assert opened[0]["location"] == shaped_key(LATEST_KEY, "portrait")


def test_a_regions_base_state_is_its_side_of_the_library(qtbot, tmp_path):
    tall = _shaped(_image("t1", "scene one", 50, 1), tmp_path, 90, 160)
    wide = _shaped(_image("w1", "scene two", 50, 2), tmp_path, 160, 90)
    view = GalleryView(FakeDB([tall, wide]))
    qtbot.addWidget(view)
    view.refresh()

    for shape, expected in (("portrait", ["t1"]), ("landscape", ["w1"])):
        key = view._slideshows.base_location(shape)
        assert key in view._item_by_key
        assert [row["prompt_id"] for row in view._slideshows.rows_at(key)] == expected
