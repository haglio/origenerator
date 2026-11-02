from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QInputDialog, QLabel, QMenu, QTabBar

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery.keys import folder_id
from origenerator.gallery.tree import settings_folder_key
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui.combination import Combination
from origenerator.gui.eliding_tab_bar import ElidingTabBar
from origenerator.gui.generate_pane import GeneratePane, parse_tabs_state
from origenerator.gui.generate_tab import GenerateTab
from origenerator.item_names import ItemNames
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.comfyui_folders import SUITE_FOLDERS


@pytest.fixture
def tabs(qtbot, tmp_path):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    db = Database(tmp_path / "test.db")
    t = GeneratePane(client, db)
    qtbot.addWidget(t)
    return t


def _pick_workflow(tab, key="sdxl_t2i"):
    index = tab._workflow_dropdown.findData(key)
    assert index >= 0, f"{key} is not in the Workflow dropdown"
    tab._workflow_dropdown.setCurrentIndex(index)
    return tab


def _sdxl_full(**over):
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params())
    params.update(over)
    return params


def _insert_gen(db, prompt_id, params, workflow_name="sdxl_t2i", workflow_version=None):
    db.insert_generation(
        prompt_id=prompt_id,
        workflow_name=workflow_name,
        workflow_version=workflow_version or WORKFLOW_REGISTRY[workflow_name].version,
        positive_prompt=params.get("positive_prompt", ""),
        negative_prompt=params.get("negative_prompt", ""),
        seed=params.get("seed"),
        params_json=json.dumps(params),
        workflow_json="{}",
    )


def _complete_gen(db, prompt_id, params, filename, subfolder="image",
                  workflow_version=None):
    _insert_gen(db, prompt_id, params, workflow_version=workflow_version)
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": subfolder}]))
    return db.get_generation(prompt_id)


def test_starts_with_one_editable_generate_tab(tabs):
    assert tabs.count() == 1
    assert isinstance(tabs.widget(0), GenerateTab)
    assert tabs.generate_tabs() == [tabs.widget(0)]


def test_uses_the_eliding_tab_bar(tabs):
    assert isinstance(tabs.tabBar(), ElidingTabBar)


def test_every_tab_including_the_first_is_closable(tabs):
    tabs._add_subtab()
    bar = tabs.tabBar()

    def close_btn(i):
        return (bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
                or bar.tabButton(i, QTabBar.ButtonPosition.LeftSide))

    assert close_btn(0) is not None
    assert close_btn(1) is not None


def test_closing_the_last_tab_leaves_a_fresh_blank_one(tabs):
    _pick_workflow(tabs.widget(0))
    gone = tabs.widget(0)

    tabs._close_subtab(0)

    assert tabs.count() == 1
    assert tabs.widget(0) is not gone
    assert tabs.widget(0).is_blank()


def test_a_double_click_on_a_tab_never_asks_for_a_name(tabs, monkeypatch):
    asked = []
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: asked.append(True) or ("X", True))

    tabs.tabBarDoubleClicked.emit(0)

    assert asked == []


def test_generate_tabs_includes_the_first_tab(tabs):
    tabs._add_subtab()
    assert len(tabs.generate_tabs()) == 2


def test_add_subtab_increases_count_and_focuses_new(tabs):
    tabs._add_subtab()
    assert tabs.count() == 2
    assert tabs.currentIndex() == 1


def test_close_subtab_removes_the_panel(tabs):
    tab = tabs._add_subtab()
    tabs._close_subtab(tabs.indexOf(tab))
    assert tabs.generate_tabs() == [tabs.widget(0)]


def test_a_middle_click_on_a_tab_closes_it(tabs, qtbot):
    keeper = tabs.widget(0)
    going = tabs._add_subtab()
    bar = tabs.tabBar()

    qtbot.mousePress(bar, Qt.MouseButton.MiddleButton,
                     pos=bar.tabRect(tabs.indexOf(going)).center())

    assert tabs.generate_tabs() == [keeper]


def test_the_pane_carries_no_corner_controls(tabs):
    assert tabs.cornerWidget(Qt.Corner.TopLeftCorner) is None
    assert tabs.cornerWidget(Qt.Corner.TopRightCorner) is None


def test_tabs_can_be_dragged_along_the_row(tabs):
    assert tabs.isMovable()


def test_the_tab_menu_closes_the_others(tabs):
    keep = tabs._add_subtab()
    tabs._add_subtab()

    tabs._close_other_subtabs(tabs.indexOf(keep))

    assert tabs.count() == 1
    assert tabs.widget(0) is keep


def test_the_tab_menu_closes_everything_to_the_right(tabs):
    first, second = tabs.widget(0), tabs._add_subtab()
    tabs._add_subtab()
    tabs._add_subtab()

    tabs._close_subtabs_to_the_right(tabs.indexOf(second))

    assert tabs.generate_tabs() == [first, second]


def test_the_tab_menu_offers_exactly_those_three_closes(tabs):
    tabs._add_subtab()
    tabs._add_subtab()
    menu = tabs._tab_menu(0)
    assert [a.text() for a in menu.actions()] == [
        "Close others", "Close to the right", "Close all",
    ]


def test_the_tab_menu_leaves_out_what_would_close_nothing(tabs):
    tabs._add_subtab()
    assert [a.text() for a in tabs._tab_menu(1).actions()] == ["Close others", "Close all"]


def _loaded_tab(tabs):
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a wizard", seed=1),
                        "sdxl_g1.png")
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(row, [row])
    return tabs.current_generate_tab()


def test_the_tab_menu_offers_the_folder_this_tab_generates_into_and_its_name(tabs):
    _loaded_tab(tabs)
    assert [a.text() for a in tabs._tab_menu(0).actions()] == ["Go to folder", "Copy name"]


def test_go_to_folder_leads_the_menu_above_the_closes(tabs):
    _loaded_tab(tabs)
    tabs._add_subtab()

    assert [a.text() for a in tabs._tab_menu(0).actions()] == [
        "Go to folder", "Copy name", "", "Close others", "Close to the right", "Close all",
    ]


def _entry(menu, text):
    (action,) = [action for action in menu.actions() if action.text() == text]
    return action


def test_copy_name_on_a_tab_copies_the_name_of_the_item_it_shows(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    row = _complete_gen(db, "g1", _sdxl_full(positive_prompt="a wizard", seed=1),
                        "sdxl_g1.png")
    names = ItemNames(db)
    names.take([row], [], {})
    tabs = GeneratePane(ComfyUIClient(folders=SUITE_FOLDERS), db, names=names)
    qtbot.addWidget(tabs)
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(row, [row])
    QApplication.clipboard().clear()

    _entry(tabs._tab_menu(0), "Copy name").trigger()

    assert QApplication.clipboard().text() == f"{folder_id(settings_folder_key(row))} 000"


def test_a_name_given_to_an_item_after_its_tab_showed_it_reaches_the_tab_and_name_line(
        qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    row = _complete_gen(db, "g1", _sdxl_full(positive_prompt="a wizard", seed=1),
                        "sdxl_g1.png")
    names = ItemNames(db)
    tabs = GeneratePane(ComfyUIClient(folders=SUITE_FOLDERS), db, names=names)
    qtbot.addWidget(tabs)
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(row, [row])
    names.take([row], [], {})

    tabs.reread_names()

    name = f"{folder_id(settings_folder_key(row))} 000"
    block = tabs.current_generate_tab()._basic_section
    on_the_block = [label.text() for label in block.findChildren(QLabel)]
    assert (tabs.tabText(0), name in on_the_block, block.isHidden()) == (name, True, False)


def test_copy_name_on_a_tab_showing_no_item_copies_the_folder_name_it_wears(tabs):
    _pick_workflow(tabs.currentWidget())
    QApplication.clipboard().clear()

    _entry(tabs._tab_menu(0), "Copy name").trigger()

    assert QApplication.clipboard().text() == tabs.tabText(0)


def test_copy_name_on_a_modify_tab_copies_the_folders_name_alone(tabs):
    tab = tabs.open_folder_modify("image/sdxl_t2i/abcdef123456", "AB12CD34", "sdxl_t2i",
                                    _sdxl_full(positive_prompt="a wizard"), [])
    QApplication.clipboard().clear()

    _entry(tabs._tab_menu(tabs.indexOf(tab)), "Copy name").trigger()

    assert QApplication.clipboard().text() == "AB12CD34"


def test_go_to_folder_asks_for_the_tab_it_was_raised_over(tabs):
    tab = _loaded_tab(tabs)
    tabs._add_subtab()
    asked = []
    tabs.folder_requested.connect(asked.append)

    tabs._tab_menu(0).actions()[0].trigger()

    assert asked == [tab.settings_folder_key()]


def test_a_tab_that_has_generated_nothing_is_offered_no_folder(tabs):
    _pick_workflow(tabs.currentWidget())
    tabs._add_subtab()

    assert [a.text() for a in tabs._tab_menu(0).actions()] == [
        "Copy name", "", "Close others", "Close to the right", "Close all",
    ]


def test_close_all_leaves_the_pane_on_its_resting_tab(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})
    tabs._add_subtab()
    tabs._add_subtab()

    tabs._close_all_subtabs()

    assert tabs.count() == 1
    assert tabs.currentWidget().is_blank()


def test_the_only_tab_has_no_menu_at_all(tabs):
    assert tabs._tab_menu(0).actions() == []
    with patch.object(QMenu, "exec") as spy:
        tabs._open_tab_menu(QPoint(5, 5))
    spy.assert_not_called()


def test_a_right_click_off_the_tabs_opens_no_menu(tabs):
    with patch.object(tabs, "_tab_menu") as spy:
        tabs._open_tab_menu(QPoint(5, 4000))
    spy.assert_not_called()


def test_a_tab_still_shows_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = GeneratePane(None, db)
    qtbot.addWidget(tabs)
    assert tabs.count() == 1
    assert tabs.widget(0)._generate_btn.isEnabled() is False


def test_open_config_is_a_no_op_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = GeneratePane(None, db)
    qtbot.addWidget(tabs)
    assert tabs.open_config("sdxl_t2i", {}) is None
    assert tabs.count() == 1


def test_open_config_takes_over_the_blank_resting_tab(tabs):
    resting = tabs.currentWidget()

    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert tabs.count() == 1
    tab = tabs.currentWidget()
    assert tab is resting
    assert tab._workflow_dropdown.currentData() == "wan22_i2v"
    assert tab._param_form.get_values()["positive_prompt"] == "a fox"


def test_open_config_adds_and_prefills_a_tab_beside_a_used_one(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})

    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert tabs.count() == 2
    tab = tabs.currentWidget()
    assert tab._workflow_dropdown.currentData() == "wan22_i2v"
    assert tab._param_form.get_values()["positive_prompt"] == "a fox"


def test_tab_text_is_the_folder_a_config_would_land_in(tabs):
    tabs.open_config("sdxl_t2i", {"positive_prompt": "a dragon"})
    idx = tabs.currentIndex()
    assert tabs.tabText(idx) == tabs.current_generate_tab().title()
    assert tabs.tabText(idx) != "New generation"


def test_tab_text_and_mark_follow_the_item_a_click_shows(tabs):
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a heron", seed=4),
                        "sdxl_g1.png")
    tabs._names.take([row], [], {})
    tabs.currentWidget()._viewport.show_media = MagicMock()

    tabs.load_selection(row, [row])

    idx = tabs.currentIndex()
    assert tabs.tabText(idx) == f"{folder_id(settings_folder_key(row))} 000"
    assert not tabs.tabIcon(idx).isNull()


def test_the_resting_tab_is_named_for_what_it_is_and_wears_no_mark(tabs):
    assert tabs.tabText(0) == "New generation"
    assert tabs.tabIcon(0).isNull()


def test_load_selection_reuses_the_blank_current_tab(tabs):
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a wizard", seed=1),
                        "sdxl_g1.png")
    tabs.currentWidget()._viewport.show_media = MagicMock()
    before = tabs.count()

    tabs.load_selection(row, [row])

    assert tabs.count() == before
    tab = tabs.current_generate_tab()
    assert tab._displayed_row is row
    assert tab._param_form.get_values()["positive_prompt"] == "a wizard"


def test_load_selection_reuses_the_tab_for_the_same_folder(tabs):
    params = _sdxl_full(positive_prompt="a wizard", seed=1)
    a = _complete_gen(tabs._db, "a", params, "sdxl_a.png")
    b = _complete_gen(tabs._db, "b", dict(params, seed=2), "sdxl_b.png")
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(a, [a, b])
    count = tabs.count()

    tabs.load_selection(b, [a, b])

    assert tabs.count() == count
    assert tabs.current_generate_tab()._displayed_row is b


def test_load_selection_reuses_the_tab_for_a_run_made_before_the_workflow_changed(tabs):
    row = _complete_gen(tabs._db, "old", _sdxl_full(positive_prompt="a wizard", seed=1),
                        "sdxl_old.png", workflow_version="v001")
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(row, [row])
    tabs.pin_current_tab()
    count = tabs.count()

    for _ in range(2):
        for tab in tabs.generate_tabs():
            tab._viewport.show_media = MagicMock()
        tabs.load_selection(row, [row])
        tabs.pin_current_tab()

    assert tabs.count() == count


def test_load_selection_replaces_the_preview_tab_rather_than_forking(tabs):
    cat = _complete_gen(tabs._db, "cat", _sdxl_full(positive_prompt="cat", seed=1), "cat.png")
    dog = _complete_gen(tabs._db, "dog", _sdxl_full(positive_prompt="dog", seed=1), "dog.png")
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(cat, [cat, dog])
    count = tabs.count()

    tabs.load_selection(dog, [cat, dog])

    assert tabs.count() == count
    assert tabs.current_generate_tab()._displayed_row is dog


def test_a_click_reads_the_table_no_more_than_the_tab_it_lands_in(tabs):
    params = _sdxl_full(positive_prompt="a wizard", seed=1)
    a = _complete_gen(tabs._db, "a", params, "sdxl_a.png")
    b = _complete_gen(tabs._db, "b", dict(params, seed=2), "sdxl_b.png")
    tabs.currentWidget()._viewport.show_media = MagicMock()
    tabs.load_selection(a, [a, b])
    tab = tabs.current_generate_tab()

    with patch.object(tabs._db, "list_generations", wraps=tabs._db.list_generations) as reads:
        tab.show_saved_generation(b, [a, b])
    shown_alone = reads.call_count
    with patch.object(tabs._db, "list_generations", wraps=tabs._db.list_generations) as reads:
        tabs.load_selection(b, [a, b])

    assert reads.call_count == shown_alone


def _two_generations(tabs):
    cat = _complete_gen(tabs._db, "cat", _sdxl_full(positive_prompt="cat", seed=1), "cat.png")
    dog = _complete_gen(tabs._db, "dog", _sdxl_full(positive_prompt="dog", seed=1), "dog.png")
    for tab in tabs.generate_tabs():
        tab._viewport.show_media = MagicMock()
    return cat, dog


def test_a_clicked_generation_makes_the_resting_tab_the_preview_tab(tabs):
    cat, _dog = _two_generations(tabs)
    resting = tabs.currentWidget()

    tabs.load_selection(cat, [cat])

    assert tabs._preview_tab is resting
    assert tabs.tabBar()._preview_index == tabs.indexOf(resting)


def test_pinning_the_front_tab_sends_the_next_click_to_a_new_one(tabs):
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    kept = tabs.current_generate_tab()

    tabs.pin_current_tab()
    tabs.load_selection(dog, [cat, dog])

    assert tabs._preview_tab is not kept
    assert kept._displayed_row is cat
    assert tabs.current_generate_tab()._displayed_row is dog
    assert tabs.count() == 2


def test_only_one_tab_is_ever_the_preview_tab(tabs):
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    tabs.pin_current_tab()
    tabs.load_selection(dog, [cat, dog])

    fresh = tabs.current_generate_tab()
    assert tabs._preview_tab is fresh
    assert tabs.tabBar()._preview_index == tabs.indexOf(fresh)


def test_pinning_a_tab_that_was_never_the_preview_one_is_harmless(tabs):
    cat, _dog = _two_generations(tabs)
    kept = tabs.current_generate_tab()
    kept.prefill("wan22_i2v", {})
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    tabs.setCurrentWidget(kept)
    tabs.pin_current_tab()

    assert tabs._preview_tab is preview


def test_the_resting_tab_opens_italic(tabs):
    assert tabs.tabBar()._preview_index == tabs.indexOf(tabs.currentWidget())


def test_picking_a_workflow_in_the_resting_tab_takes_its_italic_off(tabs):
    _pick_workflow(tabs.currentWidget())

    assert tabs.tabBar()._preview_index == -1


def test_an_opened_tab_wears_the_italic_mark_too(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})

    opened = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert tabs._preview_tab is opened
    assert tabs.tabBar()._preview_index == tabs.indexOf(opened)


def test_an_open_takes_over_a_blank_tab_that_is_not_in_front(tabs):
    blank = tabs.currentWidget()
    front = tabs._add_subtab()
    front.prefill("sdxl_t2i", {})

    opened = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert opened is blank
    assert tabs.count() == 2


def test_open_config_replaces_the_preview_tab_rather_than_forking(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})
    first = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    count = tabs.count()

    second = tabs.open_config("wan22_i2v", {"positive_prompt": "a heron"})

    assert second is first
    assert tabs.count() == count
    assert tabs.current_generate_tab() is first


def test_open_config_keeps_a_pinned_tab_and_opens_beside_it(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})
    kept = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    tabs._on_tab_generate(kept, "wan22_i2v", {})

    opened = tabs.open_config("wan22_i2v", {"positive_prompt": "a heron"})

    assert opened is not kept
    assert kept._param_form.get_values()["positive_prompt"] == "a fox"
    assert tabs._preview_tab is opened


def test_closing_the_preview_tab_leaves_no_tab_marked(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.current_generate_tab().prefill("wan22_i2v", {})
    tabs.load_selection(cat, [cat])

    tabs._close_subtab(tabs.currentIndex())

    assert tabs._preview_tab is None
    assert tabs.tabBar()._preview_index == -1


def test_the_italic_mark_follows_a_dragged_tab(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()
    tabs._add_subtab()

    tabs.tabBar().moveTab(tabs.indexOf(preview), 1)

    assert tabs.tabBar()._preview_index == tabs.indexOf(preview) == 1


def test_an_edited_tab_on_another_folder_is_left_alone(tabs):
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    pinned = tabs.current_generate_tab()
    tabs.pin_current_tab()
    pinned._param_form.set_values({"positive_prompt": "a re-roll of the cat"})

    tabs.load_selection(dog, [cat, dog])

    assert pinned._param_form.get_values()["positive_prompt"] == "a re-roll of the cat"


def test_current_generate_tab_is_the_front_tab(tabs):
    first = tabs.currentWidget()
    second = tabs._add_subtab()
    assert tabs.current_generate_tab() is second
    tabs.setCurrentIndex(tabs.indexOf(first))
    assert tabs.current_generate_tab() is first


def test_watching_a_folder_with_no_frame_yet_shows_a_waiting_note(tabs):
    tab = tabs.currentWidget()
    tab._viewport.show_message = MagicMock()
    tab.watch_folder("image/sdxl_t2i/abc", None)
    tab._viewport.show_message.assert_called_once_with("Waiting for preview…", live=True)
    assert tab.watched_key() == "image/sdxl_t2i/abc"
    assert tab.is_awaiting_frame()


def test_a_run_with_an_image_behind_it_stands_that_instead_of_a_note(tabs):
    tab = tabs.currentWidget()
    tab._viewport.show_combination = MagicMock()
    tab._viewport.show_message = MagicMock()

    tab.watch_folder("k", None, None, Combination("frame.png", "clip.webp"))

    tab._viewport.show_combination.assert_called_once_with(
        Combination("frame.png", "clip.webp"))
    tab._viewport.show_message.assert_not_called()
    assert not tab.is_awaiting_frame()


def test_the_pair_is_repainted_only_when_it_changes(tabs):
    tab = tabs.currentWidget()
    tab._viewport.show_combination = MagicMock()

    tab.watch_folder("k", None, None, Combination("frame.png", "clip.webp"))
    tab.watch_folder("k", None, None, Combination("frame.png", "clip.webp"))

    assert tab._viewport.show_combination.call_count == 1


@pytest.mark.parametrize("made_from", [Combination(), Combination(prompt_edited=True)])
def test_a_run_made_from_nothing_still_says_it_is_waiting(tabs, made_from):
    tab = tabs.currentWidget()
    tab._viewport.show_message = MagicMock()

    tab.watch_folder("k", None, None, made_from)

    tab._viewport.show_message.assert_called_once_with("Waiting for preview…", live=True)


def test_watching_prefers_a_given_wait_note(tabs):
    tab = tabs.currentWidget()
    tab._viewport.show_message = MagicMock()
    tab.watch_folder("k", None, "Waiting on 3 jobs from another app")
    assert tab._viewport.show_message.call_args.args[0] == "Waiting on 3 jobs from another app"


def test_a_wait_note_is_repainted_only_when_it_changes(tabs):
    tab = tabs.currentWidget()
    tab._viewport.show_message = MagicMock()
    tab._viewport.show_frame = MagicMock()
    tab.watch_folder("k", None, "Waiting on 3 jobs from another app")
    tab.show_live_wait("Waiting on 3 jobs from another app")
    assert tab._viewport.show_message.call_count == 1
    tab.show_live_wait("Waiting on 1 job from another app")
    assert tab._viewport.show_message.call_count == 2

    tab.show_live_frame(b"frame")

    tab._viewport.show_frame.assert_called_once_with(b"frame")
    assert not tab.is_awaiting_frame()


def test_watching_with_a_frame_puts_it_up_at_once(tabs):
    tab = tabs.currentWidget()
    tab._viewport.show_frame = MagicMock()
    tab.watch_folder("k", b"frame")
    tab._viewport.show_frame.assert_called_once_with(b"frame")


def test_watchers_of_lists_only_the_tabs_following_that_folder(tabs):
    first = tabs.currentWidget()
    second = tabs._add_subtab()
    third = tabs._add_subtab()
    first.watch_folder("k1", b"f")
    second.watch_folder("k2", b"f")
    third.watch_folder("k1", b"f")

    assert tabs.watchers_of("k1") == [first, third]
    assert tabs.tab_watching("k2") is second
    assert tabs.watchers_of("elsewhere") == []
    assert tabs.tab_watching("elsewhere") is None


def test_stop_watching_puts_the_displayed_generation_back(tabs, monkeypatch):
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("cat.png", "image"))
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    tab = tabs.current_generate_tab()
    tab._viewport.show_media = MagicMock()
    tab.watch_folder("k", b"frame")

    tab.stop_watching()

    assert tab.watched_key() is None
    tab._viewport.show_media.assert_called_once_with("cat.png", "image", cat["prompt_id"])


def test_stop_watching_a_blank_tab_leaves_it_blank(tabs):
    tab = tabs.currentWidget()
    tab._viewport.clear = MagicMock()
    tab.watch_folder("k", b"frame")

    tab.stop_watching()

    tab._viewport.clear.assert_called_once()
    assert tab.is_blank()


def test_stop_watching_a_tab_with_settings_shows_their_newest_result(tabs, monkeypatch):
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("cat.png", "image"))
    cat, _dog = _two_generations(tabs)
    tab = tabs.currentWidget()
    tab.prefill("sdxl_t2i", json.loads(cat["params_json"]))
    tab.watch_folder("k", b"frame")
    tab._viewport.show_media = MagicMock()

    tab.stop_watching()

    tab._viewport.show_media.assert_called_once_with("cat.png", "image", cat["prompt_id"])


def test_pointing_a_tab_at_a_saved_generation_ends_its_watch(tabs):
    cat, dog = _two_generations(tabs)
    tab = tabs.currentWidget()
    tab.watch_folder("k", b"frame")

    tab.show_saved_generation(dog, [cat, dog])

    assert tab.watched_key() is None


def test_show_running_generation_seeds_the_form_and_shows_no_file(tabs):
    cat, _dog = _two_generations(tabs)
    running = dict(cat, prompt_id="live", status="running", output_files="[]",
                   thumbnail_path=None)
    tab = tabs.currentWidget()
    tab._viewport.clear = MagicMock()

    tab.show_running_generation(running)

    assert tab._param_form.get_values()["positive_prompt"] == "cat"
    assert tab.displayed_row() is None
    assert tab._basic_section.isHidden()
    tab._viewport.clear.assert_called()
    assert not tab.is_blank()


def test_a_landed_image_ends_the_wait_it_was_standing_on(tabs, monkeypatch):
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("cat.png", "image"))
    cat, _dog = _two_generations(tabs)
    tab = tabs.currentWidget()
    tab._viewport.show_media = MagicMock()
    tab.watch_folder("k", None)

    tab.show_finished_media(cat)

    assert not tab.is_awaiting_frame()
    tab._viewport.show_media.assert_called_once_with("cat.png", "image", cat["prompt_id"])


def test_a_finished_result_keeps_a_prompt_typed_while_it_ran(tabs):
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a cat", seed=1),
                        "sdxl_g1.png")
    tab = _pick_workflow(tabs.current_generate_tab())
    tab._viewport.show_media = MagicMock()
    tab.note_launched("g1")
    tab._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    tabs.tab_that_launched("g1").show_completed_result(row, [row])

    assert tab._param_form.get_values()["positive_prompt"] == "a wizard mid-edit"
    assert tab._displayed_row is row


def test_a_run_no_tab_launched_belongs_to_no_tab(tabs):
    assert tabs.tab_that_launched("never-launched-here") is None
    assert tabs.tab_that_launched(None) is None


def test_double_clicking_a_tab_takes_its_italic_off(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    tabs._pin_subtab(tabs.indexOf(preview))

    assert tabs._preview_tab is None
    assert tabs.tabBar()._preview_index == -1


def test_double_clicking_a_tab_that_was_never_italic_is_harmless(tabs):
    cat, _dog = _two_generations(tabs)
    kept = tabs.current_generate_tab()
    kept.prefill("wan22_i2v", {})
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    tabs._pin_subtab(tabs.indexOf(kept))

    assert tabs._preview_tab is preview


def test_double_clicking_close_does_not_pin_the_neighbor(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()
    tabs._add_subtab()

    tabs._close_subtab(tabs.indexOf(preview) + 1)
    tabs._pin_subtab(tabs.indexOf(preview))

    assert tabs._preview_tab is preview


def test_editing_a_field_takes_the_italic_off(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    preview._param_form.set_values({"positive_prompt": "a cat wearing a hat"})

    assert tabs._preview_tab is None
    assert tabs.tabBar()._preview_index == -1


def test_an_edited_tab_is_not_replaced_by_the_next_click(tabs):
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    edited = tabs.current_generate_tab()
    edited._param_form.set_values({"positive_prompt": "a cat wearing a hat"})

    tabs.load_selection(dog, [dog])

    assert tabs.count() == 2
    assert tabs.current_generate_tab() is not edited
    assert edited._param_form.get_values()["positive_prompt"] == "a cat wearing a hat"


def test_changing_the_workflow_takes_the_italic_off(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    _pick_workflow(preview, "flux_t2i_upscaled")

    assert tabs._preview_tab is None
    assert tabs.tabBar()._preview_index == -1


def test_opening_a_generation_does_not_count_as_editing_it(tabs):
    cat, dog = _two_generations(tabs)

    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()
    tabs.load_selection(dog, [dog])

    assert tabs.count() == 1
    assert tabs.current_generate_tab() is preview
    assert tabs._preview_tab is preview


def test_opening_a_config_by_name_does_not_count_as_editing_it(tabs):
    tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="a cat"))
    opened = tabs.current_generate_tab()

    tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="a dog"))

    assert tabs.count() == 1
    assert tabs.current_generate_tab() is opened
    assert tabs._preview_tab is opened


def test_a_restored_session_does_not_come_back_edited(tabs):
    tabs.restore_state({"tabs": [_generate_tab("sdxl_t2i", {"seed": 7})], "current": 0})
    restored = tabs.current_generate_tab()

    assert restored.current_config().params["seed"] == 7
    assert tabs._preview_tab is None


def test_the_gallery_ticking_random_is_not_an_edit(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    preview.use_random_seed()

    assert tabs._preview_tab is preview


def test_editing_a_tab_that_was_never_italic_leaves_the_italic_where_it_is(tabs):
    cat, _dog = _two_generations(tabs)
    kept = tabs.current_generate_tab()
    kept.prefill("sdxl_t2i", _sdxl_full(positive_prompt="a wizard"))
    tabs.load_selection(cat, [cat])
    preview = tabs.current_generate_tab()

    kept._param_form.set_values({"positive_prompt": "a wizard on a hill"})

    assert tabs._preview_tab is preview


def _generate_tab(workflow_name, params=None, seed_is_random=True):
    return {
        "config": {"workflow_name": workflow_name,
                   "params": params or {}, "seed_is_random": seed_is_random},
    }


def test_the_run_a_tab_launched_survives_a_restart(tabs, qtbot):
    _pick_workflow(tabs.currentWidget()).note_launched("run-77")

    fresh = GeneratePane(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(tabs.capture_state())

    assert fresh.generate_tabs()[0].launched_runs() == ["run-77"]


def test_a_tab_that_never_generated_claims_no_run(tabs, qtbot):
    fresh = GeneratePane(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(tabs.capture_state())

    assert fresh.generate_tabs()[0].launched_runs() == []


def test_capture_state_lists_every_tab_and_current(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    state = tabs.capture_state()
    workflows = [tab["config"]["workflow_name"] for tab in state["tabs"]]
    assert workflows == ["sdxl_t2i", "wan22_i2v"]
    assert state["current"] == 1


def test_generate_requested_surfaces_from_the_initial_tab(tabs):
    requested = []
    tabs.generate_requested.connect(lambda wf, batch: requested.append((wf, batch)))
    tab = _pick_workflow(tabs.currentWidget())
    tab._param_form.set_values({"positive_prompt": "a cat", "seed": 3})

    tab._on_generate()

    assert requested == [("sdxl_t2i", [tab._param_form.get_values()])]


def _pick_how_many(tab, count):
    index = tab._how_many.findData(count)
    tab._how_many.setCurrentIndex(index)
    tab._how_many.activated.emit(index)


def test_one_how_many_serves_every_tab_and_each_tab_opened_after(tabs):
    first = _pick_workflow(tabs.currentWidget())
    second = tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="a fox"))

    _pick_how_many(first, 8)

    assert second._how_many.how_many() == 8
    third = tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="an owl"))
    assert third._how_many.how_many() == 8


def test_generate_requested_surfaces_from_a_forked_tab(tabs):
    requested = []
    tabs.generate_requested.connect(lambda wf, batch: requested.append(wf))
    forked = tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="a fox"))

    forked._on_generate()

    assert requested == ["sdxl_t2i"]


def test_restored_tabs_read_the_library_once_between_them(tabs, monkeypatch):
    _complete_gen(tabs._db, "pic-1", _sdxl_full(seed=7), "pic-1.png")
    db = tabs._db
    reads = []
    listing = db.list_generations
    monkeypatch.setattr(db, "list_generations", lambda: reads.append(1) or listing())

    tabs.restore_state({"tabs": [_generate_tab("sdxl_t2i", _sdxl_full(seed=seed))
                                 for seed in (7, 8, 9)], "current": 0})

    assert len(reads) == 1


def test_restore_state_rebuilds_generate_tabs(tabs):
    tabs._add_subtab()
    state = {"tabs": [
        _generate_tab("wan22_i2v", {"positive_prompt": "a fox"}),
        _generate_tab("sdxl_t2i", {"seed": 99}, seed_is_random=False),
    ], "current": 1}
    tabs.restore_state(state)
    opened = tabs.generate_tabs()
    assert len(opened) == 2
    assert opened[0]._workflow_dropdown.currentData() == "wan22_i2v"
    assert opened[0]._param_form.get_values()["positive_prompt"] == "a fox"
    assert opened[1]._workflow_dropdown.currentData() == "sdxl_t2i"
    assert opened[1]._param_form.get_values()["seed"] == 99
    assert tabs.currentIndex() == 1


def test_restore_state_skips_unknown_workflows(tabs):
    tabs.restore_state({"tabs": [
        _generate_tab("deleted_wf"), _generate_tab("wan22_i2v"),
    ]})
    opened = tabs.generate_tabs()
    assert len(opened) == 1
    assert opened[0]._workflow_dropdown.currentData() == "wan22_i2v"


def test_restore_state_keeps_the_initial_tab_when_nothing_restorable(tabs):
    tabs.restore_state({})
    tabs.restore_state({"tabs": [_generate_tab("gone")]})
    assert len(tabs.generate_tabs()) == 1
    assert tabs.count() == 1


def test_restore_state_tolerates_malformed_blobs(tabs):
    tabs.restore_state("not a dict")
    tabs.restore_state({"tabs": "not a list"})
    tabs.restore_state({"tabs": ["not a dict", {"config": {"workflow_name": "wan22_i2v"}}]})
    opened = tabs.generate_tabs()
    assert len(opened) == 1
    assert opened[0]._workflow_dropdown.currentData() == "wan22_i2v"


def test_a_malformed_snapshot_parses_to_nothing():
    assert parse_tabs_state("not a dict") == ([], 0)
    assert parse_tabs_state({"tabs": "not a list"}) == ([], 0)
    assert parse_tabs_state({}) == ([], 0)


def test_only_entries_naming_a_workflow_the_app_still_has_survive():
    restored, _ = parse_tabs_state({"tabs": [
        "not a dict", _generate_tab("deleted_wf"), _generate_tab("wan22_i2v"),
    ]})
    assert [tab.config.workflow_name for tab in restored] == ["wan22_i2v"]


def test_a_tabs_launched_runs_survive_only_as_words():
    entry = _generate_tab("wan22_i2v") | {"launched_runs": ["run-77", "", 5, None]}
    restored, _ = parse_tabs_state({"tabs": [entry]})
    assert restored[0].launched_runs == ["run-77"]

    entry = _generate_tab("wan22_i2v") | {"launched_runs": "run-77"}
    restored, _ = parse_tabs_state({"tabs": [entry]})
    assert restored[0].launched_runs == []


def test_a_tabs_layout_survives_only_as_a_table():
    entry = _generate_tab("wan22_i2v") | {"layout": {"folds": {"Seed": True}}}
    restored, _ = parse_tabs_state({"tabs": [entry]})
    assert restored[0].layout == {"folds": {"Seed": True}}

    entry = _generate_tab("wan22_i2v") | {"layout": "folded"}
    restored, _ = parse_tabs_state({"tabs": [entry]})
    assert restored[0].layout == {}


def test_the_tab_to_stand_on_is_a_number_or_the_first():
    assert parse_tabs_state({"tabs": [], "current": 2})[1] == 2
    assert parse_tabs_state({"tabs": [], "current": "two"})[1] == 0


def test_release_media_reaches_a_tab_that_is_not_in_front(tabs, tmp_path):
    doomed = tmp_path / "doomed.png"
    doomed.write_bytes(b"x")
    kept = tmp_path / "kept.png"
    kept.write_bytes(b"x")
    covered, front = tabs.current_generate_tab(), tabs._add_subtab()
    covered._viewport.show_image(doomed)
    front._viewport.show_image(kept)

    tabs.release_media([doomed])

    assert not covered._viewport.is_showing_any([doomed])
    assert front._viewport.is_showing_any([kept])


def test_a_deleted_generation_leaves_every_tab_showing_it_empty(tabs, tmp_path):
    gone, kept = tmp_path / "gone.png", tmp_path / "kept.png"
    gone.write_bytes(b"x")
    kept.write_bytes(b"x")
    doomed, other = tabs.current_generate_tab(), tabs._add_subtab()
    doomed.show_saved_generation({"prompt_id": "g1", "workflow_name": "sdxl_t2i"}, [])
    doomed._viewport.show_image(gone)
    other.show_saved_generation({"prompt_id": "g2", "workflow_name": "sdxl_t2i"}, [])
    other._viewport.show_image(kept)

    tabs.reconcile_previews({"g2"})

    assert not doomed._viewport.is_showing_any([gone])
    assert other._viewport.is_showing_any([kept])


def test_capture_restore_round_trips_config(tabs, qtbot):
    tabs.currentWidget().prefill("sdxl_t2i", {})
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox", "seed": 7})
    captured = tabs.capture_state()

    fresh = GeneratePane(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(captured)

    tabs = fresh.generate_tabs()
    assert [p._workflow_dropdown.currentData() for p in tabs] == ["sdxl_t2i", "wan22_i2v"]
    assert tabs[1]._param_form.get_values()["seed"] == 7
    assert fresh.tabText(fresh.indexOf(tabs[1])) == tabs[1].title()
    assert fresh.currentIndex() == captured["current"]
