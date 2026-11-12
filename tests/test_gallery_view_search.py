from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    Qt,
)
from PySide6.QtGui import (
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
)
from shared_ui.colors import YELLOW

from origenerator import (
    config,
    search,
)
from origenerator.gallery.collection import (
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
)
from origenerator.gallery.shapes import LANDSCAPE, SHAPE_LABELS
from origenerator.gui.gallery_view import GalleryView
from tests.gallery_view_support import (
    _NO_MOD,
    FakeActions,
    FakeDB,
    _alls,
    _at,
    _children_by_prompt,
    _collection,
    _i2v_video,
    _image,
    _image_workflow,
    _key,
    _of_both_kinds,
    _pane_holding,
    _press_ctrl_f,
    _row,
    _search_for,
    _shape,
    _shown_view_with_one_image,
    _subs,
    _tab_with_prompts,
    _top_level,
    _trash_db,
    _video_workflow,
)
from tests.text_readers import clip_reader

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


_WIDE_ENOUGH_THAT_NO_PATH_ELIDES = 2000


def _yellow_matches(field) -> int:
    return sum(sel.format.background().color() == YELLOW
               for sel in field.extraSelections())


def _find_query(view) -> QLineEdit:
    return view._find_bar.findChild(QLineEdit)


def _find_count(view) -> str:
    return view._find_bar.findChild(QLabel, "findCount").text()


def _find_next(view):
    (step,) = [button for button in view._find_bar.findChildren(QToolButton)
               if button.toolTip().startswith("Next match")]
    step.click()


def test_search_fills_the_gallery_pane_with_the_matching_generations(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"], (
        "a search fills the Gallery pane with the matching generations themselves, because a "
        "thumbnail is what the user recognizes and a folder's name, a short code, is not")
    assert view._gallery_pane.showing_search()


def test_search_leaves_the_tree_exactly_as_it_was(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)
    lora = _at(workflow, 0, 0)
    dog = _children_by_prompt(lora)["a dog"]
    before = view._tree.currentItem()

    _search_for(view, "cat")

    assert not dog.isHidden()
    assert not workflow.isExpanded()
    assert view._tree.currentItem() is before


def test_clearing_the_search_gives_the_pane_back_to_the_open_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(_children_by_prompt(lora)["a dog"])
    assert view.listed_prompt_ids() == ["i2"]

    _search_for(view, "dog")
    assert view.listed_prompt_ids() == ["i2"]

    view._search.field.setText("")

    assert view.listed_prompt_ids() == ["i2"]
    assert not view._gallery_pane.showing_search()


def test_the_tree_selection_is_what_the_search_covers(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_video_workflow(view._tree))
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["v1"]
    assert "I2V" in view._folder_path.display_text()


def test_picking_another_folder_re_asks_the_search_there(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_video_workflow(view._tree))
    _search_for(view, "cat")
    assert view.listed_prompt_ids() == ["v1"]

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert view._search.field.text() == "cat"
    assert view._gallery_pane.showing_search()
    assert view.listed_prompt_ids() == ["i1"]


def test_the_all_row_searches_the_whole_library(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    _search_for(view, "cat")

    assert set(view.listed_prompt_ids()) == {"i1", "v1"}, (
        "every other folder narrows the answer before the query does, so without All there is "
        "nowhere to stand that means everything")


def test_search_all_searches_the_whole_library_and_keeps_the_folder_highlighted(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    videos = _video_workflow(view._tree)
    view._tree.setCurrentItem(videos)
    _search_for(view, "cat")

    view._search.search_all.click()

    assert set(view.listed_prompt_ids()) == {"i1", "v1"}
    assert view._tree.currentItem() is videos
    assert "I2V" not in view._folder_path.display_text()


def test_picking_another_folder_after_search_all_searches_that_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_video_workflow(view._tree))
    _search_for(view, "cat")
    view._search.search_all.click()

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert view.listed_prompt_ids() == ["i1"]


def test_back_to_a_search_all_searches_the_whole_library_again(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    videos = _video_workflow(view._tree)
    view._tree.setCurrentItem(videos)
    _search_for(view, "cat")
    view._search.search_all.click()
    view._tree.setCurrentItem(_image_workflow(view._tree))

    view._navigation.go_back()

    assert view._tree.currentItem() is videos
    assert set(view.listed_prompt_ids()) == {"i1", "v1"}


def test_standing_on_images_searches_the_images_alone(qtbot):
    view = _of_both_kinds(qtbot)
    view._tree.setCurrentItem(_alls(view._tree)["Images"])

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]


def test_a_collection_scopes_the_search_like_any_other_row(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    rows[1]["starred"] = 1
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i2"]
    assert "Favorites" in view._folder_path.display_text()


def test_a_second_search_in_a_collection_is_still_over_the_whole_collection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2), _image("i3", "a dog", 50, 3)]
    rows[1]["starred"] = rows[2]["starred"] = 1
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    _search_for(view, "cat")
    assert view.listed_prompt_ids() == ["i2"]

    _search_for(view, "dog")

    assert view.listed_prompt_ids() == ["i3"], (
        "during a search the tiles on screen are the earlier results, so a collection's rows are "
        "read off the TOC's selection and never off what is drawn")


def test_a_folders_collection_scopes_the_search_and_names_its_path(qtbot):
    rows = [_image("i1", "a cat", 50, 1),
            _row("v1", "wan22_i2v", {"positive_prompt": "a cat", "seed": 5},
                 "wan22_i2v_00001_.mp4")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view._search.field.setFixedWidth(_WIDE_ENOUGH_THAT_NO_PATH_ELIDES)
    view.refresh()
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow.child(0))

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]
    assert view._search.field.placeholderText() == (
        f"Search {SHAPE_LABELS[LANDSCAPE]}  \u203a  All  \u203a  Images  \u203a  {workflow.text(0)}  \u203a  Latest…")


def test_the_trash_collection_searches_what_it_is_holding(qtbot):
    view = GalleryView(_trash_db(held=[("d1", _image("d1", "a cat", 50, 1)),
                                     ("d2", _image("d2", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["d1"]


def test_a_trash_search_hit_wears_the_same_buttons_as_it_does_in_the_trash(qtbot):
    actions = FakeActions()
    view = GalleryView(_trash_db(held=[("d1", _image("d1", "a cat", 50, 1))]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    _search_for(view, "cat")

    restore = view._gallery_pane._thumb_widgets["d1"]._controls.buttons()[0]
    assert restore.toolTip() == "Restore — put it and its files back where they were"
    restore.click()

    assert actions.restored == [["d1"]]


def test_a_deleted_item_is_not_an_answer_anywhere_but_the_trash(qtbot):
    view = GalleryView(_trash_db(rows=[_image("i1", "a dog", 50, 3)],
                               held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == []


def test_the_field_says_what_it_would_search(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view._search.field.setFixedWidth(_WIDE_ENOUGH_THAT_NO_PATH_ELIDES)
    view.refresh()
    assert view._search.field.placeholderText() == "Search Landscape  \u203a  All…"

    videos = _video_workflow(view._tree)
    view._tree.setCurrentItem(videos)
    assert view._search.field.placeholderText() ==         f"Search {view._tree_view.folder_path(videos)}…"

    leaf = _at(videos, 0, 0, 0, 0)
    view._tree.setCurrentItem(leaf)
    placeholder = view._search.field.placeholderText()
    assert placeholder == f"Search {view._tree_view.folder_path(leaf)}…"
    assert leaf.text(0) in placeholder
    assert videos.text(0) in placeholder

    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    assert view._search.field.placeholderText() == "Search Landscape  \u203a  All  \u203a  Latest…"


def test_the_field_shows_the_tail_of_a_path_too_long_for_it(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    videos = _video_workflow(view._tree)
    leaf = _at(videos, 0, 0, 0, 0)
    view._tree.setCurrentItem(leaf)

    metrics = view._search.field.fontMetrics()
    view._search.field.setFixedWidth(
        metrics.horizontalAdvance("Search …" + leaf.text(0)) + 24)

    scope = view._search.field._scope
    placeholder = view._search.field.placeholderText()
    assert placeholder.startswith("Search …")
    tail = placeholder[len("Search …"):]
    assert scope.endswith(tail), (
        "the folder itself and its nearest parents are the half that answers: search where?")
    assert len(tail) < len(scope)
    assert placeholder.endswith(leaf.text(0))


def test_an_empty_search_names_the_folder_it_looked_in(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    videos = _video_workflow(view._tree)
    view._tree.setCurrentItem(videos)
    _search_for(view, "dog")
    view._search._expander.expanded.emit("dog", {})

    assert videos.text(0) in view._scroll.widget().text()


def test_search_matches_words_the_prompt_did_not_use(qtbot):
    rows = [
        _image("i1", "two dolls on a couch", 50, 1),
        _image("i2", "two tall ladies at the beach", 50, 2),
        _image("i3", "a single lady in the rain", 50, 3),
        _image("i4", "an empty street", 50, 4),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "two women")

    assert set(view.listed_prompt_ids()) == {"i1", "i2"}


def test_search_stays_applied_across_a_rebuild(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")

    db.add(_image("i3", "a cat on a fence", 50, 9))
    view.refresh()

    assert set(view.listed_prompt_ids()) == {"i1", "i3"}
    assert view._gallery_pane.showing_search()


def test_toc_pane_holds_the_search_field_above_the_tree(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    toc = _pane_holding(view._tree)
    assert isinstance(view._search.field, QLineEdit)
    assert toc.isAncestorOf(view._search.field)
    section = view._tree.parentWidget().layout()
    assert section.indexOf(view._search.row) < section.indexOf(view._tree)


def test_search_all_sits_to_the_right_of_the_search_field(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    row = view._search.row.layout()
    assert row.indexOf(view._search.field) < row.indexOf(view._search.search_all)
    assert view._search.search_all.text() == "Search all"


def test_search_matches_a_generation_by_its_seed(qtbot):
    rows = [
        _image("i1", "a cat", 50, 778899),
        _image("i2", "a cat", 50, 112233),
        _image("i3", "a dog", 50, 445566),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "778899")

    assert view.listed_prompt_ids() == ["i1"], (
        "a seed names one item and rides on no folder label, so it is findable here or nowhere")


def test_a_folder_you_named_is_found_by_that_name(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    leaf = _children_by_prompt(
        _at(_image_workflow(view._tree), 0, 0))["a dog"]
    db.upsert_folder_meta(_key(leaf), custom_name="Beach trip", favorite=False,
                          level=None, ref_prompt_id=None)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    _search_for(view, "beach trip")

    assert view.listed_prompt_ids() == ["i2"]


def test_a_folder_of_your_own_made_since_the_last_rebuild_is_found_by_its_name(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    beach_trip = db.create_custom_collection("Beach trip")
    db.add_items_to_custom_collection(beach_trip, ["i2"])
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    _search_for(view, "beach trip")

    assert view.listed_prompt_ids() == ["i2"], (
        "a row is indexed under the names of the folders it sits in, so the indexing waits "
        "until this rebuild has read the user's own folders; indexed earlier it would carry the "
        "last rebuild's folder names")


def test_a_folder_is_found_by_the_code_the_tree_shows_for_it(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    code = _children_by_prompt(_at(_image_workflow(view._tree), 0, 0))["a dog"].text(0)
    view._tree.setCurrentItem(_top_level(view._tree)["All"])

    _search_for(view, code)

    assert view.listed_prompt_ids() == ["i2"]


def test_an_item_is_found_by_the_name_it_wears(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["All"])

    _search_for(view, view._item_names.of("i2"))

    assert view.listed_prompt_ids() == ["i2"]


def test_search_matches_a_prompt_word_no_folder_name_carries(qtbot):
    shared = "a cat asleep on a windowsill in the late afternoon sun, watching "
    rows = [_image("i1", shared + "sparrows", 50, 1),
            _image("i2", shared + "beetles", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    names = [row.text(0) for row in _subs(lora)]
    assert len(set(names)) == 2
    assert not any("beetles" in name for name in names)

    _search_for(view, "beetles")

    assert view.listed_prompt_ids() == ["i2"]


def test_search_ignores_the_negative_prompt(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    rows[1]["negative_prompt"] = "cat, blurry"
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]


def test_search_matches_a_generation_by_its_lora(qtbot):
    rows = [_i2v_video("v1", "styleA"), _i2v_video("v2", "styleB")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "styleA")

    assert view.listed_prompt_ids() == ["v1"]


def _section_headers(view):
    return [w for w in view._scroll.widget().findChildren(QPushButton)
            if w.objectName() == "tileGroupHeading"]


def test_the_model_lora_sort_bands_the_results_by_model_and_lora(qtbot):
    rows = [_i2v_video("v1", "styleA", prompt="a cat indoors"),
            _i2v_video("v2", "styleA", prompt="a cat outdoors"),
            _i2v_video("v3", "styleB", prompt="a cat on a fence")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)

    headings = [w.text() for w in _section_headers(view)]

    assert len(headings) == 2, (
        "a search answers two questions: newest first is where is the one made recently, and "
        "Model / LoRA is which model and LoRA was that, so there the tiles are cut into a "
        "section per combination and the answer is the heading the user stopped scrolling at")
    assert any("styleA" in h and h.endswith("(2)") for h in headings)
    assert any("styleB" in h and h.endswith("(1)") for h in headings)
    assert headings[0].endswith("(2)")


def test_a_sectioned_search_in_a_tall_gallery_leaves_each_section_its_own_height(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA", prompt="a cat"),
                               _i2v_video("v2", "styleB", prompt="a cat")]))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)
    view.resize(900, 2400)
    view.show()
    column = view._scroll.widget().layout()
    column.activate()
    section = column.itemAt(1).widget()

    assert section.height() == section.layout().heightForWidth(section.width()), (
        "sections stay their own height and the slack falls to the end of the column")


def test_the_model_lora_order_remembered_under_its_old_name_comes_back(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    view.set_search_sort("recipe")

    assert view.search_sort() == search.SORT_MODEL_LORA


def test_a_model_lora_band_folds_shut_on_its_heading(qtbot):
    rows = [_i2v_video("v1", "styleA", prompt="a cat"),
            _i2v_video("v2", "styleB", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)
    header = _section_headers(view)[0]
    section = view._scroll.widget().layout().itemAt(1).widget()
    assert section.isVisible() or not view.isVisible()

    header.click()

    assert section.isHidden(), (
        "with a dozen combinations under a broad query, shutting the ones not being asked about is "
        "what makes the sort usable")
    assert header.fold == "chevron_right"


def test_a_bands_heading_reaches_across_the_whole_column(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA", prompt="a cat"),
                               _i2v_video("v2", "styleB", prompt="a cat")]))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)
    view.resize(3000, 600)
    view.show()
    column = view._scroll.widget()
    column.layout().activate()
    headers = _section_headers(view)

    assert column.width() > max(header.sizeHint().width() for header in headers)
    assert {header.width() for header in headers} == {column.width()}, (
        "the whole row is the fold's target, which a fold control has to be when its sections "
        "are tall enough that it is aimed at after a scroll")


def test_a_folded_band_stays_folded_across_a_redraw(qtbot):
    db = FakeDB([_i2v_video("v1", "styleA", prompt="a cat"),
                 _i2v_video("v2", "styleB", prompt="a cat")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)
    shut = next(h for h in _section_headers(view) if "styleA" in h.text())
    shut.click()

    db.add(_i2v_video("v3", "styleB", prompt="a cat on a fence"))
    view.refresh()

    redrawn = next(h for h in _section_headers(view) if "styleA" in h.text())
    assert redrawn.fold == "chevron_right"
    assert next(h for h in _section_headers(view)
                if "styleB" in h.text()).fold == "chevron_down"


def test_an_empty_search_names_the_word_that_emptied_it(qtbot):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat aardvark")
    view._search._expander.expanded.emit("cat aardvark", {})

    assert view.listed_prompt_ids() == []
    assert "aardvark" in view._scroll.widget().text()


def test_an_empty_search_names_nothing_until_it_has_finished(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "aardvark")
    assert "aardvark" not in view._scroll.widget().text()

    view._search._expander.expanded.emit("aardvark", {})
    assert "aardvark" in view._scroll.widget().text()


def test_the_llm_widening_re_runs_the_search_when_it_lands(qtbot):
    rows = [_image("i1", "a lone kitten", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    assert view.listed_prompt_ids() == []

    view._search._expander.expanded.emit("cat", {"cat": ("kitten",)})

    assert view.listed_prompt_ids() == ["i1"]


def test_a_widening_for_an_abandoned_query_is_ignored(qtbot):
    rows = [_image("i1", "a lone kitten", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "dog")

    view._search._expander.expanded.emit("cat", {"cat": ("kitten",)})

    assert view.listed_prompt_ids() == ["i2"]


def test_a_search_offers_no_folder_action_for_the_folder_behind_it(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(_children_by_prompt(lora)["a dog"])

    _search_for(view, "cat")

    assert view.current_group() is None
    assert view._current_deletable_folders() == []
    assert not view._buttons.populate.isVisible()


def test_a_search_too_wide_to_draw_says_so_and_says_what_to_do(qtbot):
    rows = [_image(f"i{n}", f"a cat number {n}", 50, n) for n in range(205)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert len(view.listed_prompt_ids()) == 200, (
        "a one-word query over a full library can match most of it, and thousands of tiles in "
        "one pass locks the window, and a search does not page as the folders do: it is a "
        "narrowing tool, so the answer to too many is another word; the cap is written out "
        "here rather than read from the constant that sets it, or this test would pass at "
        "any cap at all")
    assert "205 results" in view._search._count.text()
    assert "add a word" in view._search._count.text(), (
        "the cap is stated rather than silent: the count alone would read as that many tiles to "
        "scroll to")


def test_several_hits_in_one_folder_come_back_as_that_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3), _image("i4", "a dog", 50, 4)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == [], (
        "a settings folder's rows share a prompt and differ only by seed, so a prompt match hits all "
        "of them, and near-copies of one image bury every other place the query reached")
    assert len(view._gallery_pane._listed_folders) == 1
    assert "1 result" in view._search._count.text()


def test_a_folders_lone_hit_stays_the_item_itself(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"], (
        "a folder that answered once has nothing to collapse, and a folder tile there would hide "
        "the image under a name")
    assert view._gallery_pane._listed_folders == []


def test_opening_a_result_folder_puts_the_search_away(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    (key,) = view._gallery_pane._listed_folders

    view._gallery_pane._drill_into(key)

    assert view._search.field.text() == ""
    assert not view._gallery_pane.showing_search()
    assert set(view.listed_prompt_ids()) == {"i1", "i2"}


def test_nothing_is_searched_until_a_beat_of_quiet(qtbot):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._search.field.setText("cat")

    assert not view._gallery_pane.showing_search(), (
        "a search scores the whole library and rebuilds the pane; one per character churns the "
        "results under a word still being typed")
    assert view._search._timer.isActive()

    view._search._timer.stop()
    view._search._run_pending()

    assert view.listed_prompt_ids() == ["i1"]


def test_a_query_under_three_characters_searches_nothing(qtbot):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._search.field.setText("ca")

    assert not view._search._timer.isActive(), (
        "one or two letters reach a large part of any library through stemming alone")
    assert not view._gallery_pane.showing_search()

    _search_for(view, "cat")
    assert view._gallery_pane.showing_search()

    view._search.field.setText("ca")
    assert not view._gallery_pane.showing_search()


def test_a_searchs_hits_are_what_the_slideshow_would_play(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a dog", 50, 3)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert [row["prompt_id"] for row in view.rows_to_play()] == ["i1", "i2"], (
        "a search's results are gathered exactly as a collection's are, and sitting through "
        "what one turned up is a good reason to have run it")
    assert "these results" in view._buttons.slideshow.toolTip()


def test_ctrl_f_opens_the_find_over_the_front_tabs_prompts(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat")
    negative.setPlainText("no cat")
    assert not view._find_bar.isVisible()

    assert _press_ctrl_f(view, monkeypatch) is True

    assert view._find_bar.isVisible()
    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 2"


def test_ctrl_f_reaches_the_find_from_inside_a_prompt_field(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _tab_with_prompts(view)
    monkeypatch.setattr(view, "_gallery_owns_keys", lambda **_kw: False)

    assert _press_ctrl_f(view, monkeypatch) is True, (
        "the field being typed in is exactly where a find is reached for")

    assert view._find_bar.isVisible()


def test_the_find_locates_a_word_inside_the_open_tabs_prompt(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, _negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat on a windowsill, watching sparrows and more sparrows")
    _press_ctrl_f(view, monkeypatch)

    _find_query(view).setText("sparrows")

    assert _find_count(view) == "1 of 2"
    assert positive.textCursor().position() == positive.toPlainText().find("sparrows")


def test_an_open_find_follows_a_prompt_as_it_gains_and_loses_boxes(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    prompt = _tab_with_prompts(view)._param_form._widgets["positive_prompt"]
    _press_ctrl_f(view, monkeypatch)
    _find_query(view).setText("dog")
    first = prompt.boxes()[0]

    first.setPlainText(" ".join(["cat"] * 75) + " dog")
    qtbot.waitUntil(lambda: len(prompt.boxes()) == 2, timeout=5000)
    assert _find_count(view) == "1 of 1"

    first.setPlainText("cat")
    qtbot.waitUntil(lambda: len(prompt.boxes()) == 1, timeout=5000)
    assert _find_count(view) == "1 of 1"


def test_stepping_the_find_walks_the_matches_and_wraps(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat")
    negative.setPlainText("no cat")
    _press_ctrl_f(view, monkeypatch)
    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 2"

    _find_next(view)
    assert _find_count(view) == "2 of 2"
    assert _yellow_matches(negative) == 1
    assert _yellow_matches(positive) == 0

    _find_next(view)
    assert _find_count(view) == "1 of 2"
    assert _yellow_matches(positive) == 1
    assert _yellow_matches(negative) == 0


def test_esc_closes_the_find_and_leaves_no_highlights(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, _negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat")
    _press_ctrl_f(view, monkeypatch)
    _find_query(view).setText("cat")
    assert positive.extraSelections()

    handled = view.eventFilter(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, _NO_MOD))

    assert handled is True
    assert not view._find_bar.isVisible()
    assert not positive.extraSelections()


def test_ctrl_f_falls_back_to_the_tree_find_with_no_prompts_in_front(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)

    _press_ctrl_f(view, monkeypatch)

    assert not view._find_bar.isVisible()
    assert view.focusWidget() is view._search.field


def test_switching_tabs_points_an_open_find_at_the_new_prompts(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    first = _tab_with_prompts(view)
    first.prompt_fields()[0].setPlainText("a cat")
    view._generate_pane._add_subtab()
    second = _tab_with_prompts(view)
    second.prompt_fields()[0].setPlainText("a cat and a cat")
    view._generate_pane.setCurrentWidget(first)
    _press_ctrl_f(view, monkeypatch)
    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 1"

    view._generate_pane.setCurrentWidget(second)

    assert _find_count(view) == "1 of 2"
    assert not first.prompt_fields()[0].extraSelections()


def test_closing_the_searched_tab_puts_an_open_find_away(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _tab_with_prompts(view)
    _press_ctrl_f(view, monkeypatch)
    assert view._find_bar.isVisible()

    view._generate_pane._close_subtab(view._generate_pane.currentIndex())

    assert not view._find_bar.isVisible()


def test_ctrl_f_after_the_searched_prompts_are_gone_opens_over_the_ones_in_front(
        qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    searched = _tab_with_prompts(view).prompt_fields()
    _press_ctrl_f(view, monkeypatch)
    view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, _NO_MOD))
    view._generate_pane._close_subtab(view._generate_pane.currentIndex())
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(not shiboken6.isValid(field) for field in searched)
    in_front = _tab_with_prompts(view)
    in_front.prompt_fields()[0].setPlainText("a cat")

    assert _press_ctrl_f(view, monkeypatch) is True

    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 1"


def test_picking_another_workflow_points_an_open_find_at_its_prompts(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    searched = _tab_with_prompts(view).prompt_fields()
    _press_ctrl_f(view, monkeypatch)

    tab = _tab_with_prompts(view, "flux_t2i_upscaled")
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(not shiboken6.isValid(field) for field in searched)
    tab.prompt_fields()[0].setPlainText("a cat and a cat")

    _find_query(view).setText("cat")
    _find_next(view)

    assert _find_count(view) == "2 of 2"
    assert _press_ctrl_f(view, monkeypatch) is True


def test_a_search_asks_its_question_once_through_a_rebuild(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    asked = []
    run = view._search.run
    view._search.run = lambda: asked.append("run") or run()

    view.refresh()

    assert asked == ["run"]


def test_with_no_row_selected_a_search_covers_the_gallerys_own_rows_and_not_the_trash(qtbot):
    view = GalleryView(_trash_db(rows=[_image("i1", "a cat", 50, 1)],
                                 held=[("d1", _image("d1", "a cat", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    _shape(view._tree).setCurrentItem(None)

    assert view.search_scope().ids == {"i1"}


def test_an_open_find_counts_again_as_a_prompt_is_typed_in(qtbot, tmp_path):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    tab = _tab_with_prompts(view)
    positive, _negative = tab.prompt_fields()
    positive.setPlainText("a cat")
    view._open_find()
    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 1"

    positive.setPlainText("a cat and a cat")

    assert _find_count(view) == "1 of 2"


def test_following_a_link_puts_a_running_search_away(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    assert view._gallery_pane.showing_search()

    view.follow_link("i2")

    assert not view._gallery_pane.showing_search()
    assert view._search.field.text() == ""
