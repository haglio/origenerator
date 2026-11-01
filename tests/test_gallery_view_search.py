from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import (
    QCoreApplication,
    QEvent,
    Qt,
)
from PyQt6.QtGui import (
    QKeyEvent,
)
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
)
from shared_ui.colors import YELLOW

from origenerator import (
    search,
)
from origenerator.gallery.collection import (
    FAVORITES_KEY,
    RECENTS_KEY,
    TRASH_KEY,
)
from origenerator.gallery.sides import LANDSCAPE, SIDE_LABELS
from origenerator.gui.gallery_view import GalleryView
from tests.gallery_view_support import (
    _NO_MOD,
    FakeDB,
    _alls,
    _at,
    _bin_db,
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
    _shown_view_with_one_image,
    _subs,
    _tab_with_prompts,
    _top_level,
    _video_workflow,
)

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


def _yellow_matches(field) -> int:
    """How many of ``field``'s find highlights are the current-match yellow. The
    find re-lays every field's highlights on each step, so across the fields
    exactly one of them is ever yellow."""
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


def test_search_fills_the_browser_pane_with_the_matching_generations(qtbot):
    # The whole point of moving the search off the tree: the answer is the
    # thumbnails themselves, in the middle pane, not a narrowed list of folder
    # names whose labels are truncated prompt headlines.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]
    assert view._browser.showing_search()


def test_search_leaves_the_tree_exactly_as_it_was(qtbot):
    # It used to hide every non-matching row and expand paths down to the hits.
    # Now nothing in the tree moves, so clearing the field puts the user back in
    # the folder they were standing in rather than somewhere the search wandered.
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

    assert view.listed_prompt_ids() == ["i2"]   # back in the folder that was open
    assert not view._browser.showing_search()


def test_the_tree_selection_is_what_the_search_covers(qtbot):
    # The tree scopes the query rather than being narrowed by it: standing in a
    # folder asks the question there, and a hit outside it is not an answer.
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_video_workflow(view._tree))
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["v1"]
    assert "I2V" in view._folder_path.display_text()  # the header says where it looked


def test_picking_another_folder_re_asks_the_search_there(qtbot):
    # Picking a folder mid-search is a new scope, not an exit — the same
    # question, asked somewhere else, with the field left as it was.
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_video_workflow(view._tree))
    _search_for(view, "cat")
    assert view.listed_prompt_ids() == ["v1"]

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert view._search.field.text() == "cat"
    assert view._browser.showing_search()
    assert view.listed_prompt_ids() == ["i1"]


def test_the_all_row_searches_the_whole_library(qtbot):
    # What All is for: every other folder narrows the answer before the query
    # does, so without a row above Images and Videos there is nowhere to stand
    # that means everything.
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    _search_for(view, "cat")

    assert set(view.listed_prompt_ids()) == {"i1", "v1"}


def test_standing_on_images_searches_the_images_alone(qtbot):
    view = _of_both_kinds(qtbot)
    view._tree.setCurrentItem(_alls(view._tree)["Images"])

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]


def test_a_collection_scopes_the_search_like_any_other_row(qtbot):
    # A collection is a set of generations, so standing in one and searching it
    # is the obvious thing to try — and it used to quietly search everything.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    rows[1]["starred"] = 1
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i2"]     # the favorited one alone
    assert "Favorites" in view._folder_path.display_text()


def test_a_folders_collection_scopes_the_search_and_names_its_path(qtbot):
    rows = [_image("i1", "a cat", 50, 1),
            _row("v1", "wan22_i2v", {"positive_prompt": "a cat", "seed": 5},
                 "wan22_i2v_00001_.mp4")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view._search.field.setFixedWidth(2000)
    view.refresh()
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow.child(0))

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]
    assert view._search.field.placeholderText() == (
        f"Search {SIDE_LABELS[LANDSCAPE]}  ›  All  ›  Images  ›  {workflow.text(0)}  ›  Latest…")


def test_the_trash_collection_searches_what_it_is_holding(qtbot):
    # A deleted row is out of the gallery's own list and lives only in the bin,
    # so a Trash search finds nothing at all unless the bin is indexed too.
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1)),
                                     ("d2", _image("d2", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["d1"]


def test_a_deleted_item_is_not_an_answer_anywhere_but_the_trash(qtbot):
    # The bin shares the index so its collection can be searched; it must not leak
    # into a search of the gallery, where those items are gone.
    view = GalleryView(_bin_db(rows=[_image("i1", "a dog", 50, 3)],
                               held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    _search_for(view, "cat")

    assert view.listed_prompt_ids() == []


def test_the_field_says_what_it_would_search(qtbot):
    # The whole path down to the selected folder, not the folder's own name: a
    # folder is named by a code, which places nothing on its own.
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view._search.field.setFixedWidth(2000)  # room for any path, so nothing elides
    view.refresh()
    # The side is part of the path: an All row is one half of the library.
    assert view._search.field.placeholderText() == "Search Landscape  ›  All…"

    videos = _video_workflow(view._tree)
    view._tree.setCurrentItem(videos)
    assert view._search.field.placeholderText() ==         f"Search {view._tree_view.breadcrumb(videos)}…"

    leaf = _at(videos, 0, 0, 0, 0)
    view._tree.setCurrentItem(leaf)
    placeholder = view._search.field.placeholderText()
    assert placeholder == f"Search {view._tree_view.breadcrumb(leaf)}…"
    assert leaf.text(0) in placeholder      # right down to the folder itself
    assert videos.text(0) in placeholder    # and every branch above it

    view._tree.setCurrentItem(_collection(view, RECENTS_KEY))
    assert view._search.field.placeholderText() == "Search Landscape  ›  All  ›  Latest…"


def test_the_field_shows_the_tail_of_a_path_too_long_for_it(qtbot):
    # A path that doesn't fit is elided from the left, keeping the folder itself
    # and its nearest parents — the half that answers "search where?".
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    videos = _video_workflow(view._tree)
    leaf = _at(videos, 0, 0, 0, 0)
    view._tree.setCurrentItem(leaf)

    # Wide enough for the folder's own name and little else.
    metrics = view._search.field.fontMetrics()
    view._search.field.setFixedWidth(
        metrics.horizontalAdvance("Search …" + leaf.text(0)) + 24)

    scope = view._search.field._scope
    placeholder = view._search.field.placeholderText()
    assert placeholder.startswith("Search …")       # said to be cut, at the front
    tail = placeholder[len("Search …"):]
    assert scope.endswith(tail) and len(tail) < len(scope)  # elided from the left
    assert placeholder.endswith(leaf.text(0))       # the folder itself survives


def test_an_empty_search_names_the_folder_it_looked_in(qtbot):
    # A query that would answer elsewhere looks identical to one that answers
    # nowhere, and the fix for the first is a wider folder, not a different word.
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
    # "two women" has to reach "two dolls" and "two tall ladies" alike — a
    # substring filter finds neither, which is what made the old one useless.
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

    # Both two-subject rows, and neither the lone lady nor the empty street:
    # every word of the query has to be satisfied, so "two" rules i3 out.
    assert set(view.listed_prompt_ids()) == {"i1", "i2"}


def test_search_stays_applied_across_a_rebuild(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")

    db.add(_image("i3", "a cat on a fence", 50, 9))  # a new match lands...
    view.refresh()                                   # ...triggering a rebuild

    # The results are still on screen, and the newcomer joined them.
    assert set(view.listed_prompt_ids()) == {"i1", "i3"}
    assert view._browser.showing_search()


def test_toc_pane_holds_the_search_field_above_the_tree(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    toc = _pane_holding(view._tree)
    assert isinstance(view._search.field, QLineEdit)
    assert toc.isAncestorOf(view._search.field)
    # it leads its own section of the pane, above the tree it searches across.
    section = view._search.field.parentWidget().layout()
    assert section.indexOf(view._search.field) < section.indexOf(view._tree)


def test_search_matches_a_generation_by_its_seed(qtbot):
    # A seed names one item, and rides on no folder label, so it is findable
    # here or nowhere — and it lands on that item, not on its folder's siblings.
    rows = [
        _image("i1", "a cat", 50, 778899),
        _image("i2", "a cat", 50, 112233),
        _image("i3", "a dog", 50, 445566),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "778899")

    assert view.listed_prompt_ids() == ["i1"]


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
    # Naming a folder by a code took every prompt word out of the tree, so the
    # search has to reach the rows themselves — matching on a word that appears
    # nowhere in any folder name, only in the prompt one generation ran.
    shared = "a cat asleep on a windowsill in the late afternoon sun, watching "
    rows = [_image("i1", shared + "sparrows", 50, 1),
            _image("i2", shared + "beetles", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    names = [row.text(0) for row in _subs(lora)]
    assert len(set(names)) == 2                      # a code apiece, never shared
    assert not any("beetles" in name for name in names)

    _search_for(view, "beetles")

    assert view.listed_prompt_ids() == ["i2"]


def test_search_ignores_the_negative_prompt(qtbot):
    # A negative prompt lists what a run was told to keep OUT, so a hit there is
    # the opposite of what was asked for. On a real library three quarters of one
    # query's results came from negatives — the bulk of "this doesn't work".
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    rows[1]["negative_prompt"] = "cat, blurry"   # a run that asked for no cat
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
    """The fold headers of the open search's model + LoRA bands, in shown order."""
    return [w for w in view._scroll.widget().findChildren(QPushButton)
            if w.objectName() == "tileGroupHeading"]


def test_the_model_lora_sort_bands_the_results_by_model_and_lora(qtbot):
    # The other question a search answers: not "where is it" but "which
    # model and LoRA was that" — so the hits are cut into a labelled band per
    # model + LoRA combination instead of interleaved.
    rows = [_i2v_video("v1", "styleA", prompt="a cat indoors"),
            _i2v_video("v2", "styleA", prompt="a cat outdoors"),
            _i2v_video("v3", "styleB", prompt="a cat on a fence")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)

    headings = [w.text() for w in _section_headers(view)]

    assert len(headings) == 2
    assert any("styleA" in h and h.endswith("(2)") for h in headings)
    assert any("styleB" in h and h.endswith("(1)") for h in headings)
    assert headings[0].endswith("(2)")   # the bigger band leads


def test_the_model_lora_order_remembered_under_its_old_name_comes_back(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    view.set_search_sort("recipe")

    assert view.search_sort() == search.SORT_MODEL_LORA


def test_a_model_lora_band_folds_shut_on_its_heading(qtbot):
    # With a dozen combinations under a broad query, being able to shut the ones
    # you are not asking about is what makes the sort usable rather than sorted.
    rows = [_i2v_video("v1", "styleA", prompt="a cat"),
            _i2v_video("v2", "styleB", prompt="a cat")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.set_search_sort(search.SORT_MODEL_LORA)
    header = _section_headers(view)[0]
    band = view._scroll.widget().layout().itemAt(1).widget()
    assert band.isVisible() or not view.isVisible()  # laid out open to begin with

    header.click()

    assert band.isHidden()
    assert header.fold == "chevron_right"   # and the chevron says so


def test_a_folded_band_stays_folded_across_a_redraw(qtbot):
    # A rebuild, a landing generation or a widening all redraw the pane; springing
    # the bands you shut back open each time would make folding pointless.
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
    assert redrawn.fold == "chevron_right"   # still shut
    assert next(h for h in _section_headers(view)
                if "styleB" in h.text()).fold == "chevron_down"  # the other still open


def test_an_empty_search_names_the_word_that_emptied_it(qtbot):
    # Every word has to be satisfied, so with several typed the one thing worth
    # knowing is which to drop — "no results" alone leaves the user re-typing.
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
    # The deterministic tier draws first and the model only ever adds words, so a
    # widening that arrives improves a view the user is already looking at.
    rows = [_image("i1", "a lone kitten", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    assert view.listed_prompt_ids() == []   # nothing says "cat"

    view._search._expander.expanded.emit("cat", {"cat": ("kitten",)})

    assert view.listed_prompt_ids() == ["i1"]


def test_a_widening_for_an_abandoned_query_is_ignored(qtbot):
    # A slow answer can land after the user has typed on; widening results for a
    # query they are no longer running would put items on screen they can't
    # account for.
    rows = [_image("i1", "a lone kitten", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "dog")

    view._search._expander.expanded.emit("cat", {"cat": ("kitten",)})

    assert view.listed_prompt_ids() == ["i2"]


def test_a_search_offers_no_folder_action_for_the_folder_behind_it(qtbot):
    # The tree still has a row selected while a search runs, but that folder is
    # not what the pane shows — so Enhance All, auto-generate and delete-the-
    # folder must not fire against something off screen.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(_children_by_prompt(lora)["a dog"])

    _search_for(view, "cat")

    assert view.current_group() is None
    assert view._current_deletable_folders() == []
    assert not view._bank.auto.isVisible()


def test_a_search_too_wide_to_draw_says_so_and_says_what_to_do(qtbot):
    # A one-word query over a full library can match most of it, and thousands of
    # tiles in one pass locks the window. The cap is stated rather than silent —
    # "2,000 results" alone would read as 2,000 tiles you could scroll to. The cap
    # is written out rather than read from SEARCH_DRAW_LIMIT: taken from the
    # constant that sets it, this test passes at any cap at all.
    rows = [_image(f"i{n}", f"a cat number {n}", 50, n) for n in range(205)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert len(view.listed_prompt_ids()) == 200
    assert "205 results" in view._search._count.text()
    assert "add a word" in view._search._count.text()


def test_several_hits_in_one_folder_come_back_as_that_folder(qtbot):
    # Rows in a settings folder share a prompt and differ only by seed, so a
    # prompt match hits all of them — and eight near-copies of one image bury
    # every other place the query reached.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3), _image("i4", "a dog", 50, 4)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == []       # no loose thumbnails...
    assert len(view._browser._listed_folders) == 1  # ...one folder standing for all three
    assert "1 result" in view._search._count.text()


def test_a_folders_lone_hit_stays_the_item_itself(qtbot):
    # Collapsing is for the near-copies; a folder that answered once has nothing
    # to collapse, and a folder tile there would hide the image under a name.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert view.listed_prompt_ids() == ["i1"]
    assert view._browser._listed_folders == []


def test_opening_a_result_folder_puts_the_search_away(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    (key,) = view._browser._listed_folders

    view._browser._drill_into(key)   # the path a folder tile's click takes

    assert view._search.field.text() == ""
    assert not view._browser.showing_search()
    assert set(view.listed_prompt_ids()) == {"i1", "i2"}  # standing in the folder


def test_nothing_is_searched_until_a_beat_of_quiet(qtbot):
    # A search scores the whole library and rebuilds the pane; one per character
    # churns the results under a word still being typed.
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._search.field.setText("cat")

    assert not view._browser.showing_search()   # typed, not yet searched
    assert view._search._timer.isActive()

    view._search._timer.stop()
    view._search._run_pending()

    assert view.listed_prompt_ids() == ["i1"]


def test_a_query_under_three_characters_searches_nothing(qtbot):
    # One or two letters reach a large fraction of any library through stemming
    # alone, so an as-you-type search would answer the first keystroke of every
    # query with most of the gallery.
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._search.field.setText("ca")

    assert not view._search._timer.isActive()
    assert not view._browser.showing_search()

    _search_for(view, "cat")
    assert view._browser.showing_search()

    view._search.field.setText("ca")   # back under the floor: the search is over
    assert not view._browser.showing_search()


def test_a_searchs_hits_are_what_the_slideshow_would_play(qtbot):
    # A search's results are gathered exactly as a collection's are, and
    # sitting through what one turned up is a good reason to have run it.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a dog", 50, 3)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")

    assert [row["prompt_id"] for row in view.rows_to_play()] == ["i1", "i2"]
    assert "these results" in view._bank.slideshow.toolTip()


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
    # Focus in a prompt field hands Delete and Undo back to the widget; Ctrl+F
    # still has to arrive, since the field you're typing in is exactly where you
    # reach for a find.
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _tab_with_prompts(view)
    monkeypatch.setattr(view, "_gallery_owns_keys", lambda **_kw: False)

    assert _press_ctrl_f(view, monkeypatch) is True

    assert view._find_bar.isVisible()


def test_the_find_locates_a_word_inside_the_open_tabs_prompt(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, _negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat on a windowsill, watching sparrows and more sparrows")
    _press_ctrl_f(view, monkeypatch)

    _find_query(view).setText("sparrows")

    assert _find_count(view) == "1 of 2"
    assert positive.textCursor().position() == positive.toPlainText().find("sparrows")


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
    # The yellow highlight moved with it, on into the next field.
    assert _yellow_matches(negative) == 1 and _yellow_matches(positive) == 0

    _find_next(view)
    assert _find_count(view) == "1 of 2"           # and around again
    assert _yellow_matches(positive) == 1 and _yellow_matches(negative) == 0


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
    assert not positive.extraSelections()  # a closed find leaves no marks


def test_ctrl_f_falls_back_to_the_tree_find_with_no_prompts_in_front(qtbot, tmp_path, monkeypatch):
    # The resting tab has no form until a workflow is picked, so there are no
    # prompts to search; the chord goes to the one search the window still has
    # rather than doing nothing.
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)

    _press_ctrl_f(view, monkeypatch)

    assert not view._find_bar.isVisible()
    assert view.focusWidget() is view._search.field


def test_switching_tabs_points_an_open_find_at_the_new_prompts(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    first = _tab_with_prompts(view)
    first.prompt_fields()[0].setPlainText("a cat")
    view._info_tabs._add_subtab()          # a second tab, its prompts still empty
    second = _tab_with_prompts(view)
    second.prompt_fields()[0].setPlainText("a cat and a cat")
    view._info_tabs.setCurrentWidget(first)
    _press_ctrl_f(view, monkeypatch)
    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 1"

    view._info_tabs.setCurrentWidget(second)

    assert _find_count(view) == "1 of 2"
    assert not first.prompt_fields()[0].extraSelections()  # the old tab's paint is gone


def test_closing_the_searched_tab_puts_an_open_find_away(qtbot, tmp_path, monkeypatch):
    # The blank tab that replaces it has no prompts, so the find has nothing left
    # to sit over.
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _tab_with_prompts(view)
    _press_ctrl_f(view, monkeypatch)
    assert view._find_bar.isVisible()

    view._info_tabs._close_subtab(view._info_tabs.currentIndex())

    assert not view._find_bar.isVisible()


def test_ctrl_f_after_the_searched_prompts_are_gone_opens_over_the_ones_in_front(
        qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    searched = _tab_with_prompts(view).prompt_fields()
    _press_ctrl_f(view, monkeypatch)
    view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, _NO_MOD))
    view._info_tabs._close_subtab(view._info_tabs.currentIndex())
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(sip.isdeleted(field) for field in searched)
    in_front = _tab_with_prompts(view)
    in_front.prompt_fields()[0].setPlainText("a cat")

    assert _press_ctrl_f(view, monkeypatch) is True

    _find_query(view).setText("cat")
    assert _find_count(view) == "1 of 1"


def test_picking_another_workflow_points_an_open_find_at_its_prompts(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    searched = _tab_with_prompts(view).prompt_fields()
    _press_ctrl_f(view, monkeypatch)

    panel = _tab_with_prompts(view, "flux_t2i_upscaled")
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(sip.isdeleted(field) for field in searched)
    panel.prompt_fields()[0].setPlainText("a cat and a cat")

    _find_query(view).setText("cat")
    _find_next(view)

    assert _find_count(view) == "2 of 2"
    assert _press_ctrl_f(view, monkeypatch) is True
