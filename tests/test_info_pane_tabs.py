import json
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.workflows import WORKFLOW_REGISTRY


@pytest.fixture
def tabs(qtbot, tmp_path):
    client = ComfyUIClient()
    db = Database(tmp_path / "test.db")
    t = InfoPaneTabs(client, db)  # starts with one editable config tab
    qtbot.addWidget(t)
    return t


def _pick_workflow(panel, key="sdxl_t2i"):
    """Answer a fresh tab's workflow picker, so it has a param form to poke at."""
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData(key))
    return panel


def _sdxl_full(**over):
    """A full sdxl param set, as a real generation would store it."""
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params())
    params.update(over)
    return params


def _insert_gen(db, prompt_id, params, workflow_name="sdxl_t2i"):
    """Insert a generation whose params_json reflects its real settings — stamped
    with the workflow's current version, as a run made by this app would be (the
    settings signature folds the version in, so a stale one would split this row
    from a live config tab's key)."""
    db.insert_generation(
        prompt_id=prompt_id,
        workflow_name=workflow_name,
        workflow_version=WORKFLOW_REGISTRY[workflow_name].version,
        positive_prompt=params.get("positive_prompt", ""),
        negative_prompt=params.get("negative_prompt", ""),
        seed=params.get("seed"),
        params_json=json.dumps(params),
        workflow_json="{}",
    )


def _complete_gen(db, prompt_id, params, filename, subfolder="image"):
    """A completed generation with an output file, ready to be shown in a tab."""
    _insert_gen(db, prompt_id, params)
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": subfolder}]))
    return db.get_generation(prompt_id)


# --- every tab is a plain editable config tab -------------------------------

def test_starts_with_one_editable_config_tab(tabs):
    assert tabs.count() == 1
    assert isinstance(tabs.widget(0), GenerateConfigPanel)
    assert tabs.config_panels() == [tabs.widget(0)]


def test_uses_the_eliding_tab_bar(tabs):
    from origenerator.gui.eliding_tab_bar import ElidingTabBar
    assert isinstance(tabs.tabBar(), ElidingTabBar)


def test_every_tab_including_the_first_is_closable(tabs):
    # Installing a custom bar must precede setTabsClosable, or the per-tab close
    # button silently vanishes — this guards that ordering. No tab is special: the
    # very first one closes just like a forked one.
    from PyQt6.QtWidgets import QTabBar
    tabs._add_subtab()  # a second tab at index 1
    bar = tabs.tabBar()

    def close_btn(i):
        return (bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
                or bar.tabButton(i, QTabBar.ButtonPosition.LeftSide))

    assert close_btn(0) is not None
    assert close_btn(1) is not None


def test_closing_the_last_tab_leaves_a_fresh_blank_one(tabs):
    # The pane is never empty: closing the last tab used to strand a black
    # rectangle with nothing in it to click, so a resting tab takes its place.
    _pick_workflow(tabs.widget(0))
    gone = tabs.widget(0)

    tabs._close_subtab(0)

    assert tabs.count() == 1
    assert tabs.widget(0) is not gone
    assert tabs.widget(0).is_blank()


def test_a_double_click_on_a_tab_never_asks_for_a_name(tabs, monkeypatch):
    # The gesture used to open a rename box. A tab is named after what it shows
    # now, so nothing should be asking the user for one.
    from PyQt6.QtWidgets import QInputDialog
    asked = []
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: asked.append(True) or ("X", True))

    tabs.tabBarDoubleClicked.emit(0)

    assert asked == []


def test_config_panels_includes_the_first_tab(tabs):
    tabs._add_subtab()
    assert len(tabs.config_panels()) == 2


def test_add_subtab_increases_count_and_focuses_new(tabs):
    tabs._add_subtab()
    assert tabs.count() == 2
    assert tabs.currentIndex() == 1


def test_close_subtab_removes_the_panel(tabs):
    panel = tabs._add_subtab()
    tabs._close_subtab(tabs.indexOf(panel))
    assert tabs.config_panels() == [tabs.widget(0)]


def test_the_pane_carries_no_corner_controls(tabs):
    # The "+" is gone with the empty pane it existed to refill, and close-all with
    # it: a tab is always open, and the tab menu closes the rest.
    assert tabs.cornerWidget(Qt.Corner.TopLeftCorner) is None
    assert tabs.cornerWidget(Qt.Corner.TopRightCorner) is None


# --- the tab row: reorder by drag, close by menu ----------------------------

def test_tabs_can_be_dragged_along_the_row(tabs):
    # The order is the user's, not the order things happened to open in.
    assert tabs.isMovable()


def test_the_tab_menu_closes_the_others(tabs):
    keep = tabs._add_subtab()
    tabs._add_subtab()  # three open; the middle one is the keeper

    tabs._close_other_subtabs(tabs.indexOf(keep))

    assert tabs.count() == 1
    assert tabs.widget(0) is keep


def test_the_tab_menu_closes_everything_to_the_right(tabs):
    first, second = tabs.widget(0), tabs._add_subtab()
    tabs._add_subtab()
    tabs._add_subtab()  # four open

    tabs._close_subtabs_to_the_right(tabs.indexOf(second))

    assert tabs.config_panels() == [first, second]  # the ones at or before it


def test_the_tab_menu_offers_exactly_those_three_closes(tabs):
    tabs._add_subtab()
    tabs._add_subtab()  # three open, so the first tab can do all of them
    menu = tabs._tab_menu(0)
    assert [a.text() for a in menu.actions()] == [
        "Close others", "Close to the right", "Close all",
    ]


def test_the_tab_menu_leaves_out_what_would_close_nothing(tabs):
    # An entry that can't do anything isn't listed dead — it isn't listed. The
    # last tab of two has nothing to its right, but there is still an "all".
    tabs._add_subtab()
    assert [a.text() for a in tabs._tab_menu(1).actions()] == ["Close others", "Close all"]


def test_close_all_leaves_the_pane_on_its_resting_tab(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})
    tabs._add_subtab()
    tabs._add_subtab()  # three open

    tabs._close_all_subtabs()

    assert tabs.count() == 1
    assert tabs.currentWidget().is_blank()  # a fresh one, not a survivor


def test_the_only_tab_has_no_menu_at_all(tabs):
    # Nothing to close beside it and nothing to its right; an empty box flashed
    # at the cursor would be worse than no menu.
    from PyQt6.QtCore import QPoint

    assert tabs._tab_menu(0).actions() == []
    with patch.object(QMenu, "exec") as spy:
        tabs._open_tab_menu(QPoint(5, 5))
    spy.assert_not_called()


def test_a_right_click_off_the_tabs_opens_no_menu(tabs):
    from PyQt6.QtCore import QPoint

    with patch.object(tabs, "_tab_menu") as spy:
        tabs._open_tab_menu(QPoint(5, 4000))  # below the row: no tab there
    spy.assert_not_called()


# --- a read-only gallery (no client) ---------------------------------------

def test_a_tab_still_shows_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = InfoPaneTabs(None, db)  # a read-only gallery: nothing to run
    qtbot.addWidget(tabs)
    assert tabs.count() == 1  # a tab still shows, Generate disabled
    assert tabs.widget(0)._generate_btn.isEnabled() is False


def test_open_config_is_a_no_op_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = InfoPaneTabs(None, db)
    qtbot.addWidget(tabs)
    assert tabs.open_config("sdxl_t2i", {}) is None
    assert tabs.count() == 1  # still just the initial tab


# --- opening / reusing config tabs -----------------------------------------

def test_open_config_takes_over_the_blank_resting_tab(tabs):
    # Nothing has been done in the pane's "New generation" tab, so the opened
    # configuration lands in it rather than beside it.
    resting = tabs.currentWidget()

    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert tabs.count() == 1
    panel = tabs.currentWidget()
    assert panel is resting
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_open_config_adds_and_prefills_a_tab_beside_a_used_one(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})  # the resting tab is now someone's work

    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert tabs.count() == 2
    panel = tabs.currentWidget()
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_tab_text_is_the_folder_a_config_would_land_in(tabs):
    tabs.open_config("sdxl_t2i", {"positive_prompt": "a dragon"})
    idx = tabs.currentIndex()
    assert tabs.tabText(idx) == tabs.current_config_panel().title()  # its folder
    assert tabs.tabText(idx) != "New generation"


def test_tab_text_and_mark_follow_the_item_a_click_shows(tabs):
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a heron", seed=4),
                        "sdxl_g1.png")
    tabs.currentWidget()._preview.show_media = MagicMock()

    tabs.load_selection(row, [row])

    idx = tabs.currentIndex()
    assert tabs.tabText(idx) == "sdxl_g1.png"    # the item, by its file
    assert not tabs.tabIcon(idx).isNull()        # and wearing its kind's mark


def test_the_resting_tab_is_named_for_what_it_is_and_wears_no_mark(tabs):
    assert tabs.tabText(0) == "New generation"
    assert tabs.tabIcon(0).isNull()


# --- load_selection: single-click a browser thumbnail ----------------------

def test_load_selection_reuses_the_blank_current_tab(tabs):
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a wizard", seed=1),
                        "sdxl_g1.png")
    tabs.currentWidget()._preview.show_media = MagicMock()
    before = tabs.count()

    tabs.load_selection(row, [row])

    assert tabs.count() == before  # the blank first tab was reused, not forked
    panel = tabs.current_config_panel()
    assert panel._displayed_row is row
    assert panel._param_form.get_values_static()["positive_prompt"] == "a wizard"


def test_load_selection_reuses_the_tab_for_the_same_folder(tabs):
    params = _sdxl_full(positive_prompt="a wizard", seed=1)
    a = _complete_gen(tabs._db, "a", params, "sdxl_a.png")
    b = _complete_gen(tabs._db, "b", dict(params, seed=2), "sdxl_b.png")  # same folder, new seed
    tabs.currentWidget()._preview.show_media = MagicMock()
    tabs.load_selection(a, [a, b])
    count = tabs.count()

    tabs.load_selection(b, [a, b])  # same settings folder as what the tab shows

    assert tabs.count() == count  # reused in place, no new tab
    assert tabs.current_config_panel()._displayed_row is b


def test_load_selection_replaces_the_preview_tab_rather_than_forking(tabs):
    # Browsing item after item costs one tab, not one per item: each single click
    # lands in the same italic tab.
    cat = _complete_gen(tabs._db, "cat", _sdxl_full(positive_prompt="cat", seed=1), "cat.png")
    dog = _complete_gen(tabs._db, "dog", _sdxl_full(positive_prompt="dog", seed=1), "dog.png")
    tabs.currentWidget()._preview.show_media = MagicMock()
    tabs.load_selection(cat, [cat, dog])
    count = tabs.count()

    tabs.load_selection(dog, [cat, dog])  # a different settings folder

    assert tabs.count() == count
    assert tabs.current_config_panel()._displayed_row is dog


# --- the preview tab: one click borrows it, a double-click keeps it ---------

def _two_generations(tabs):
    cat = _complete_gen(tabs._db, "cat", _sdxl_full(positive_prompt="cat", seed=1), "cat.png")
    dog = _complete_gen(tabs._db, "dog", _sdxl_full(positive_prompt="dog", seed=1), "dog.png")
    for panel in tabs.config_panels():
        panel._preview.show_media = MagicMock()
    return cat, dog


def test_a_clicked_generation_makes_the_resting_tab_the_preview_tab(tabs):
    cat, _dog = _two_generations(tabs)
    resting = tabs.currentWidget()

    tabs.load_selection(cat, [cat])

    assert tabs._preview_panel is resting
    assert tabs.tabBar()._preview_index == tabs.indexOf(resting)


def test_pinning_the_front_tab_sends_the_next_click_to_a_new_one(tabs):
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    kept = tabs.current_config_panel()

    tabs.pin_current_tab()  # the double-click half of the gesture
    tabs.load_selection(dog, [cat, dog])

    assert tabs._preview_panel is not kept
    assert kept._displayed_row is cat  # the pinned tab kept what it was showing
    assert tabs.current_config_panel()._displayed_row is dog
    assert tabs.count() == 2


def test_only_one_tab_is_ever_the_preview_tab(tabs):
    # The new tab a click opens after a pin takes the italic over; nothing else
    # should still be wearing it.
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    tabs.pin_current_tab()
    tabs.load_selection(dog, [cat, dog])

    fresh = tabs.current_config_panel()
    assert tabs._preview_panel is fresh
    assert tabs.tabBar()._preview_index == tabs.indexOf(fresh)


def test_pinning_a_tab_that_was_never_the_preview_one_is_harmless(tabs):
    cat, _dog = _two_generations(tabs)
    kept = tabs.current_config_panel()
    kept.prefill("wan22_i2v", {})    # a tab of its own, never the italic one
    tabs.load_selection(cat, [cat])  # which opens beside it
    preview = tabs.current_config_panel()

    tabs.setCurrentWidget(kept)
    tabs.pin_current_tab()

    assert tabs._preview_panel is preview  # the italic stayed where it was


def test_the_resting_tab_opens_italic(tabs):
    # Nothing has been done in it, so the next open takes it over — which is
    # what the slant says.
    assert tabs.tabBar()._preview_index == tabs.indexOf(tabs.currentWidget())


def test_picking_a_workflow_in_the_resting_tab_takes_its_italic_off(tabs):
    # It stops being the tab an open may throw away the moment it holds a choice
    # someone made.
    _pick_workflow(tabs.currentWidget())

    assert tabs.tabBar()._preview_index == -1


def test_an_opened_tab_wears_the_italic_mark_too(tabs):
    # open_config is someone asking for this configuration by name — a strip
    # click, a queue row, a combine handoff. Still "show me this", so it lands in
    # the preview tab and is drawn slanted like a browsed one.
    tabs.currentWidget().prefill("sdxl_t2i", {})  # so the open forks a tab of its own

    opened = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert tabs._preview_panel is opened
    assert tabs.tabBar()._preview_index == tabs.indexOf(opened)


def test_an_open_takes_over_a_blank_tab_that_is_not_in_front(tabs):
    # The rule is about the tab, not about which one is selected: an untouched
    # "New generation" is taken over wherever in the row it sits.
    blank = tabs.currentWidget()
    front = tabs._add_subtab()
    front.prefill("sdxl_t2i", {})

    opened = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})

    assert opened is blank
    assert tabs.count() == 2  # the blank one was used up, not added to


def test_open_config_replaces_the_preview_tab_rather_than_forking(tabs):
    # A second "Edit…" costs no more tabs than the first: it lands in
    # the italic tab the last one left.
    tabs.currentWidget().prefill("sdxl_t2i", {})
    first = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    count = tabs.count()

    second = tabs.open_config("wan22_i2v", {"positive_prompt": "a heron"})

    assert second is first
    assert tabs.count() == count
    assert tabs.current_config_panel() is first


def test_open_config_keeps_a_pinned_tab_and_opens_beside_it(tabs):
    # Generating from a tab pins it, so the next open can't take it over.
    tabs.currentWidget().prefill("sdxl_t2i", {})
    kept = tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    tabs._on_panel_generate(kept, "wan22_i2v", {})  # its Generate pins it upright

    opened = tabs.open_config("wan22_i2v", {"positive_prompt": "a heron"})

    assert opened is not kept
    assert kept._param_form.get_values_static()["positive_prompt"] == "a fox"
    assert tabs._preview_panel is opened


def test_closing_the_preview_tab_leaves_no_tab_marked(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.current_config_panel().prefill("wan22_i2v", {})  # a tab that stays
    tabs.load_selection(cat, [cat])                       # the italic one beside it

    tabs._close_subtab(tabs.currentIndex())

    assert tabs._preview_panel is None
    assert tabs.tabBar()._preview_index == -1


def test_the_italic_mark_follows_a_dragged_tab(tabs):
    # The bar draws the mark by index, and a drag changes it.
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_config_panel()
    tabs._add_subtab()  # a second tab, after it

    tabs.tabBar().moveTab(tabs.indexOf(preview), 1)

    assert tabs.tabBar()._preview_index == tabs.indexOf(preview) == 1


def test_an_edited_tab_on_another_folder_is_left_alone(tabs):
    # A pinned tab holding a different folder must not be clobbered by a click
    # elsewhere: the click opens the preview tab instead.
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    pinned = tabs.current_config_panel()
    tabs.pin_current_tab()
    pinned._param_form.set_values({"positive_prompt": "a re-roll of the cat"})

    tabs.load_selection(dog, [cat, dog])

    assert pinned._param_form.get_values_static()["positive_prompt"] == "a re-roll of the cat"


def test_current_config_panel_is_the_front_tab(tabs):
    first = tabs.currentWidget()
    second = tabs._add_subtab()
    assert tabs.current_config_panel() is second
    tabs.setCurrentIndex(tabs.indexOf(first))
    assert tabs.current_config_panel() is first


# --- a tab follows the run it launched into, or was pointed at ------------------

def test_watching_a_folder_with_no_frame_yet_shows_a_waiting_note(tabs):
    # "Select a generation to preview" would misdescribe a running run, so a
    # queued one with no frame yet says it is waiting — marked live, so the pane
    # can be double-clicked open before the first frame.
    panel = tabs.currentWidget()
    panel._preview.show_message = MagicMock()
    panel.watch_folder("image/sdxl_t2i/abc", None)
    panel._preview.show_message.assert_called_once_with("Waiting for preview…", live=True)
    assert panel.watched_key() == "image/sdxl_t2i/abc"
    assert panel.is_awaiting_frame()


def test_watching_prefers_a_given_wait_note(tabs):
    # "Waiting for preview…" says nothing about why. When the caller knows what the
    # run is stuck behind, that replaces it.
    panel = tabs.currentWidget()
    panel._preview.show_message = MagicMock()
    panel.watch_folder("k", None, "Waiting behind 3 jobs from another app")
    assert panel._preview.show_message.call_args.args[0] == "Waiting behind 3 jobs from another app"


def test_a_wait_note_is_repainted_only_when_it_changes(tabs):
    # The poll re-reads the wait every tick; the same words must not be painted
    # over themselves each time, and a frame ends the wait for good.
    panel = tabs.currentWidget()
    panel._preview.show_message = MagicMock()
    panel._preview.show_frame = MagicMock()
    panel.watch_folder("k", None, "Waiting behind 3 jobs from another app")
    panel.show_live_wait("Waiting behind 3 jobs from another app")
    assert panel._preview.show_message.call_count == 1
    panel.show_live_wait("Waiting behind 1 job from another app")
    assert panel._preview.show_message.call_count == 2

    panel.show_live_frame(b"frame")

    panel._preview.show_frame.assert_called_once_with(b"frame")
    assert not panel.is_awaiting_frame()  # the frame is the answer now


def test_watching_with_a_frame_puts_it_up_at_once(tabs):
    panel = tabs.currentWidget()
    panel._preview.show_frame = MagicMock()
    panel.watch_folder("k", b"frame")
    panel._preview.show_frame.assert_called_once_with(b"frame")


def test_watchers_of_lists_only_the_tabs_following_that_folder(tabs):
    first = tabs.currentWidget()
    second = tabs._add_subtab()
    third = tabs._add_subtab()
    first.watch_folder("k1", b"f")
    second.watch_folder("k2", b"f")
    third.watch_folder("k1", b"f")

    assert tabs.watchers_of("k1") == [first, third]
    assert tabs.panel_watching("k2") is second
    assert tabs.watchers_of("elsewhere") == [] and tabs.panel_watching("elsewhere") is None


def test_stop_watching_puts_the_displayed_generation_back(tabs, monkeypatch):
    # A run that ended with nothing to show leaves the tab where it was: on the
    # generation it was displaying, rather than on a stale partial frame.
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("cat.png", "image"))
    cat, dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat, dog])
    panel = tabs.current_config_panel()
    panel._preview.show_media = MagicMock()
    panel.watch_folder("k", b"frame")

    panel.stop_watching()

    assert panel.watched_key() is None
    panel._preview.show_media.assert_called_once_with("cat.png", "image")


def test_stop_watching_a_blank_tab_leaves_it_blank(tabs):
    panel = tabs.currentWidget()
    panel._preview.clear = MagicMock()
    panel.watch_folder("k", b"frame")

    panel.stop_watching()

    panel._preview.clear.assert_called_once()
    assert panel.is_blank()


def test_stop_watching_a_tab_with_settings_shows_their_newest_result(tabs, monkeypatch):
    # Nothing on display but a recipe on the form: the tab goes back to what a
    # tab with those settings idles on, the newest thing they made.
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("cat.png", "image"))
    cat, _dog = _two_generations(tabs)
    panel = tabs.currentWidget()
    panel.prefill("sdxl_t2i", json.loads(cat["params_json"]))
    panel.watch_folder("k", b"frame")
    panel._preview.show_media = MagicMock()

    panel.stop_watching()

    panel._preview.show_media.assert_called_once_with("cat.png", "image")


def test_pointing_a_tab_at_a_saved_generation_ends_its_watch(tabs):
    # The next frame would land over the picture just put here.
    cat, dog = _two_generations(tabs)
    panel = tabs.currentWidget()
    panel.watch_folder("k", b"frame")

    panel.show_saved_generation(dog, [cat, dog])

    assert panel.watched_key() is None


def test_show_running_generation_seeds_the_form_and_shows_no_file(tabs):
    # What a click on a folder's live tile lands in a tab: the run's own settings
    # on the form, as a clicked thumbnail's would be, and no picture, footer or
    # generation on display until the run lands. The tab is named after the
    # folder the run will land in, so it is not blank and the next open forks.
    cat, _dog = _two_generations(tabs)
    running = dict(cat, prompt_id="live", status="running", output_files="[]",
                   thumbnail_path=None)
    panel = tabs.currentWidget()
    panel._preview.clear = MagicMock()

    panel.show_running_generation(running)

    assert panel._param_form.get_values_static()["positive_prompt"] == "cat"
    assert panel.displayed_row() is None
    assert panel._metadata_block.isHidden()
    panel._preview.clear.assert_called()
    assert not panel.is_blank()


def test_a_landed_picture_ends_the_wait_it_was_standing_on(tabs, monkeypatch):
    # show_finished_media puts the landed file where the frames were; the tab
    # is no longer waiting for anything, so a later poll must not paint a wait
    # note over the picture.
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("cat.png", "image"))
    cat, _dog = _two_generations(tabs)
    panel = tabs.currentWidget()
    panel._preview.show_media = MagicMock()
    panel.watch_folder("k", None)

    panel.show_finished_media(cat)

    assert not panel.is_awaiting_frame()
    panel._preview.show_media.assert_called_once_with("cat.png", "image")


def test_a_finished_result_keeps_a_prompt_typed_while_it_ran(tabs):
    # A Generate finishing in the tab that launched it lands its result there, but
    # must not wipe a prompt the user has since typed into that same tab's form.
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a cat", seed=1),
                        "sdxl_g1.png")
    panel = _pick_workflow(tabs.current_config_panel())
    panel._preview.show_media = MagicMock()
    panel.note_launched("g1")  # this tab's own Generate started it
    panel._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    tabs.panel_that_launched("g1").show_completed_result(row, [row])

    assert panel._param_form.get_values_static()["positive_prompt"] == "a wizard mid-edit"
    assert panel._displayed_row is row  # the finished result is on display


def test_a_run_no_tab_launched_belongs_to_no_tab(tabs):
    # The gallery's own launches — the folder tile's "+", the auto-generate loop —
    # are nobody's Generate. Their results must not land in whatever tab happens to
    # be in front: filling the pane's blank resting tab with a picture stopped it
    # being the tab a click loads into, so the next click opened one beside it.
    assert tabs.panel_that_launched("never-launched-here") is None
    assert tabs.panel_that_launched(None) is None


# --- double-clicking a tab keeps it ----------------------------------------

def test_double_clicking_a_tab_takes_its_italic_off(tabs):
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_config_panel()

    tabs._pin_subtab(tabs.indexOf(preview))

    assert tabs._preview_panel is None
    assert tabs.tabBar()._preview_index == -1


def test_double_clicking_a_tab_that_was_never_italic_is_harmless(tabs):
    cat, _dog = _two_generations(tabs)
    kept = tabs.current_config_panel()
    kept.prefill("wan22_i2v", {})    # a tab of someone's own, not the resting one
    tabs.load_selection(cat, [cat])  # the italic one opens beside it
    preview = tabs.current_config_panel()

    tabs._pin_subtab(tabs.indexOf(kept))

    assert tabs._preview_panel is preview  # the italic stayed where it was


def test_double_clicking_close_does_not_pin_the_neighbor(tabs):
    # Double-clicking the ✕ closes a config tab on its first click; the
    # remaining tabs shift left and the completing double-click lands on the
    # neighbor, firing tabBarDoubleClicked. That stray click must not keep a tab
    # the user never meant to keep.
    cat, _dog = _two_generations(tabs)
    tabs.load_selection(cat, [cat])
    preview = tabs.current_config_panel()
    tabs._add_subtab()  # a tab after it, closed out from under the cursor

    tabs._close_subtab(tabs.indexOf(preview) + 1)
    tabs._pin_subtab(tabs.indexOf(preview))  # the completing click, now over it

    assert tabs._preview_panel is preview


# --- session capture / restore ---------------------------------------------

def _config_tab(workflow_name, params=None, seed_is_random=True):
    return {
        "config": {"workflow_name": workflow_name,
                   "params": params or {}, "seed_is_random": seed_is_random},
    }


def test_the_run_a_tab_launched_survives_a_restart(tabs, qtbot):
    # A tab's Cancel and progress fill follow the run it started, so which run that
    # was has to come back with the tab — otherwise a restart mid-generation
    # reopens the tab with an idle button over a job still cooking.
    _pick_workflow(tabs.currentWidget()).note_launched("run-77")

    fresh = InfoPaneTabs(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(tabs.capture_state())

    assert fresh.config_panels()[0].launched_runs() == ["run-77"]


def test_a_tab_that_never_generated_claims_no_run(tabs, qtbot):
    fresh = InfoPaneTabs(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(tabs.capture_state())

    assert fresh.config_panels()[0].launched_runs() == []


def test_capture_state_lists_every_tab_and_current(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})                  # the initial tab
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})   # index 1, current
    state = tabs.capture_state()
    workflows = [tab["config"]["workflow_name"] for tab in state["tabs"]]
    assert workflows == ["sdxl_t2i", "wan22_i2v"]
    assert state["current"] == 1


def test_generate_requested_surfaces_from_the_initial_tab(tabs):
    # The tab strip re-emits each tab's Generate so the gallery can launch it as a
    # re-roll — here from the initial tab. It carries the workflow and form params.
    requested = []
    tabs.generate_requested.connect(lambda wf, params: requested.append((wf, params)))
    panel = _pick_workflow(tabs.currentWidget())
    panel._param_form.set_values({"positive_prompt": "a cat", "seed": 3})

    panel._on_generate()

    assert requested == [("sdxl_t2i", panel._param_form.get_values_static())]


def test_generate_requested_surfaces_from_a_forked_tab(tabs):
    # A tab forked after construction must also have its Generate wired, like
    # title_changed — so a Generate from any tab reaches the gallery.
    requested = []
    tabs.generate_requested.connect(lambda wf, params: requested.append(wf))
    forked = tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="a fox"))

    forked._on_generate()

    assert requested == ["sdxl_t2i"]


def test_restore_state_rebuilds_config_tabs(tabs):
    tabs._add_subtab()  # a pre-existing tab, to be replaced
    state = {"tabs": [
        _config_tab("wan22_i2v", {"positive_prompt": "a fox"}),
        _config_tab("sdxl_t2i", {"seed": 99}, seed_is_random=False),
    ], "current": 1}
    tabs.restore_state(state)
    panels = tabs.config_panels()
    assert len(panels) == 2  # every prior tab was replaced
    assert panels[0]._workflow_combo.currentData() == "wan22_i2v"
    assert panels[0]._param_form.get_values_static()["positive_prompt"] == "a fox"
    assert panels[1]._workflow_combo.currentData() == "sdxl_t2i"
    assert panels[1]._param_form.get_values_static()["seed"] == 99
    assert tabs.currentIndex() == 1


def test_restore_state_skips_unknown_workflows(tabs):
    tabs.restore_state({"tabs": [
        _config_tab("deleted_wf"), _config_tab("wan22_i2v"),
    ]})
    panels = tabs.config_panels()
    assert len(panels) == 1
    assert panels[0]._workflow_combo.currentData() == "wan22_i2v"


def test_restore_state_keeps_the_initial_tab_when_nothing_restorable(tabs):
    tabs.restore_state({})
    tabs.restore_state({"tabs": [_config_tab("gone")]})
    assert len(tabs.config_panels()) == 1  # the initial tab is left in place
    assert tabs.count() == 1


def test_restore_state_tolerates_malformed_blobs(tabs):
    # A corrupt/cross-version state value must not brick startup.
    tabs.restore_state("not a dict")
    tabs.restore_state({"tabs": "not a list"})
    tabs.restore_state({"tabs": ["not a dict", {"config": {"workflow_name": "wan22_i2v"}}]})
    panels = tabs.config_panels()
    assert len(panels) == 1  # only the one valid entry survived
    assert panels[0]._workflow_combo.currentData() == "wan22_i2v"


def test_release_media_reaches_a_tab_that_is_not_in_front(tabs, tmp_path):
    # Browsing generation after generation spreads them across tabs, and a tab
    # out of sight holds its file open exactly as firmly as the front one — which
    # is what used to make deleting a previewed item fail on Windows.
    doomed = tmp_path / "doomed.png"
    doomed.write_bytes(b"x")
    kept = tmp_path / "kept.png"
    kept.write_bytes(b"x")
    behind, front = tabs.current_config_panel(), tabs._add_subtab()
    behind._preview.show_image(doomed)
    front._preview.show_image(kept)

    tabs.release_media([doomed])

    assert not behind._preview.is_showing_any([doomed])  # the tab behind let go
    assert front._preview.is_showing_any([kept])         # the other one kept its item


def test_capture_restore_round_trips_config(tabs, qtbot):
    tabs.currentWidget().prefill("sdxl_t2i", {})  # a plain sdxl tab
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox", "seed": 7})  # current
    captured = tabs.capture_state()

    fresh = InfoPaneTabs(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(captured)

    panels = fresh.config_panels()
    assert [p._workflow_combo.currentData() for p in panels] == ["sdxl_t2i", "wan22_i2v"]
    assert panels[1]._param_form.get_values_static()["seed"] == 7
    # A tab is named by what it shows, so its name comes back with its config.
    assert fresh.tabText(fresh.indexOf(panels[1])) == panels[1].title()
    assert fresh.currentIndex() == captured["current"]
