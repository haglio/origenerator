import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
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


def _strip_ids(tabs):
    strip = tabs.currentWidget()._strip
    return [strip._list.itemAt(i).widget().prompt_id for i in range(strip._list.count())]


def _has_ancestor(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


# --- every tab is a plain editable config tab -------------------------------

def test_starts_with_one_editable_config_tab(tabs):
    assert tabs.count() == 1
    assert isinstance(tabs.widget(0), GenerateConfigPanel)
    assert tabs._config_panels() == [tabs.widget(0)]


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


def test_closing_the_last_tab_is_allowed(tabs):
    tabs._close_subtab(0)
    assert tabs.count() == 0
    assert tabs._config_panels() == []


def test_the_first_tab_is_renamable(tabs, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
    tabs._rename_subtab(0)
    assert tabs.widget(0)._custom_title == "Renamed"
    assert tabs.tabText(0) == "Renamed"


def test_config_panels_includes_the_first_tab(tabs):
    tabs._add_subtab()
    assert len(tabs._config_panels()) == 2


def test_thumbnail_strip_sits_within_the_tabbed_content(tabs):
    panel = tabs._add_subtab()
    assert _has_ancestor(panel._strip, tabs)


def test_add_subtab_increases_count_and_focuses_new(tabs):
    tabs._add_subtab()
    assert tabs.count() == 2
    assert tabs.currentIndex() == 1


def test_the_plus_button_adds_a_config_tab(tabs):
    tabs._add_btn.click()
    assert tabs.count() == 2
    assert isinstance(tabs.currentWidget(), GenerateConfigPanel)


def test_close_subtab_removes_and_tears_down(tabs):
    panel = tabs._add_subtab()
    with patch.object(panel, "teardown", wraps=panel.teardown) as spy:
        tabs._close_subtab(tabs.indexOf(panel))
    spy.assert_called_once()
    assert tabs._config_panels() == [tabs.widget(0)]


# --- close all --------------------------------------------------------------

def test_close_all_wears_the_tabs_own_close_mark(tabs):
    # Two spellings of "close" in one row read as two different controls: the
    # tabs' ✕ is the style's mark, so the corner button borrows it rather than
    # typing a ✕ character of its own next to "All".
    from origenerator.gui import icons

    assert "✕" not in tabs._close_all_btn.text()
    assert tabs._close_all_btn.text() == "All"
    expected = icons.tab_close_icon().pixmap(tabs._close_all_btn.iconSize())
    assert tabs._close_all_btn.icon().pixmap(
        tabs._close_all_btn.iconSize()).toImage() == expected.toImage()


def test_close_all_icon_matches_the_size_a_tab_draws_its_close_mark(tabs):
    # Same mark at a different scale would still look like a different control.
    from PyQt6.QtWidgets import QStyle

    indicator = tabs.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
    assert tabs._close_all_btn.iconSize().width() == indicator


def test_both_corner_buttons_stand_the_same_height(tabs):
    # Close-all carries an icon and "+" a bare glyph, so left alone the two sit at
    # different heights in one row — the same mismatched look this pairing is
    # meant to end.
    tabs.resize(900, 300)
    tabs.show()
    tabs._corner.layout().activate()
    assert tabs._add_btn.height() == tabs._close_all_btn.height()


def test_close_all_button_empties_the_pane_in_one_click(tabs):
    tabs._add_subtab()
    tabs._add_subtab()  # three open tabs

    tabs._close_all_btn.click()

    assert tabs.count() == 0
    assert tabs._config_panels() == []


def test_close_all_tears_down_every_panel(tabs):
    # Each closed tab must release what it holds, exactly as its own ✕ does —
    # closing in bulk is no excuse to leak a panel's timers/handles.
    panels = [tabs.widget(0), tabs._add_subtab(), tabs._add_subtab()]
    with ExitStack() as stack:
        spies = [
            stack.enter_context(patch.object(p, "teardown", wraps=p.teardown))
            for p in panels
        ]
        tabs.close_all_subtabs()
        for spy in spies:
            spy.assert_called_once()


def test_close_all_on_an_already_empty_pane_is_harmless(tabs):
    tabs.close_all_subtabs()
    tabs.close_all_subtabs()  # nothing left to walk
    assert tabs.count() == 0


def test_close_all_is_disabled_only_while_the_pane_is_empty(tabs):
    assert tabs._close_all_btn.isEnabled()  # one tab open
    tabs.close_all_subtabs()
    assert not tabs._close_all_btn.isEnabled()  # nothing left to close
    tabs._add_btn.click()
    assert tabs._close_all_btn.isEnabled()  # a fresh tab re-arms it


def test_close_all_leaves_the_add_button_usable(tabs):
    # An emptied pane is not a dead end: "+" still opens a fresh tab.
    tabs.close_all_subtabs()
    tabs._add_btn.click()
    assert tabs.count() == 1
    assert isinstance(tabs.currentWidget(), GenerateConfigPanel)


def test_the_add_button_is_still_on_screen_with_no_tabs_left(tabs):
    # It isn't enough that "+" still works when clicked in a test: Qt sizes the
    # corner to the tab bar, so an emptied pane used to flatten both buttons to
    # zero pixels and leave nothing to click at all.
    from PyQt6.QtWidgets import QApplication

    tabs.resize(900, 300)
    tabs.show()
    QApplication.processEvents()
    standing = tabs._add_btn.height()

    tabs.close_all_subtabs()
    QApplication.processEvents()

    assert tabs._add_btn.height() == standing
    assert tabs._close_all_btn.height() == standing


def test_close_all_sits_left_of_the_add_button(tabs):
    # The gap between them means a miss on the "+" a user clicks constantly
    # doesn't empty the pane instead.
    row = tabs._corner.layout()
    assert [row.itemAt(i).widget() for i in range(row.count())] == [
        tabs._close_all_btn, tabs._add_btn,
    ]


def _laid_out(tabs):
    from PyQt6.QtWidgets import QApplication

    tabs.resize(900, 300)
    tabs.show()
    QApplication.processEvents()


def test_the_tab_row_buttons_follow_the_last_tab(tabs):
    # They belong to the tab strip, so they stand where a browser's new-tab button
    # stands — right after the tabs — rather than marooned at the far right with a
    # gap of nothing between.
    _laid_out(tabs)
    assert tabs._corner.x() == tabs.tabBar().width()

    tabs._add_subtab()  # a second tab widens the row; the buttons move along with it
    _laid_out(tabs)
    assert tabs._corner.x() == tabs.tabBar().width()


def test_the_tab_row_buttons_stand_exactly_as_tall_as_the_row(tabs):
    # Taller than the tabs, they hung below the strip into the pane underneath.
    _laid_out(tabs)
    row_height = tabs.tabBar().sizeHint().height()
    assert tabs._corner.height() == row_height
    assert tabs._add_btn.height() == row_height
    assert tabs._close_all_btn.height() == row_height


def test_the_tabs_never_run_under_the_buttons(tabs):
    # Enough tabs to fill the row must not slide beneath the two buttons, which
    # are painted over the same strip and would swallow the last tab's ✕.
    for _ in range(12):
        tabs._add_subtab()
    _laid_out(tabs)
    assert tabs.tabBar().width() <= tabs._corner.x()
    assert tabs._corner.geometry().right() <= tabs.width()


def test_the_tab_row_buttons_wear_the_tab_style(tabs):
    assert tabs._add_btn.objectName() == "tabBarButton"
    assert tabs._close_all_btn.objectName() == "tabBarButton"


# --- a read-only gallery (no client) ---------------------------------------

def test_a_tab_still_shows_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = InfoPaneTabs(None, db)  # a read-only gallery: nothing to run
    qtbot.addWidget(tabs)
    assert tabs.count() == 1  # a tab still shows, Generate disabled
    assert tabs.widget(0)._generate_btn.isEnabled() is False
    assert not tabs._add_btn.isVisible()
    # Neither corner button shows: with no "+" to reopen one, a close-all would
    # strand the pane empty for the rest of the session.
    assert tabs._corner.isHidden()


def test_open_config_is_a_no_op_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = InfoPaneTabs(None, db)
    qtbot.addWidget(tabs)
    assert tabs.open_config("sdxl_t2i", {}) is None
    assert tabs.count() == 1  # still just the initial tab


# --- opening / reusing config tabs -----------------------------------------

def test_open_config_adds_and_prefills_tab(tabs):
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    assert tabs.count() == 2
    panel = tabs.currentWidget()
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_open_config_seeds_the_new_tab_strip(tabs):
    _insert_gen(tabs._db, "x1", _sdxl_full(positive_prompt="cat"))
    tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="cat"))
    assert _strip_ids(tabs) == ["x1"]


def test_tab_text_follows_gallery_folder_name(tabs):
    tabs.open_config("sdxl_t2i", {"positive_prompt": "a dragon"})
    idx = tabs.currentIndex()
    assert tabs.tabText(idx) == "SDXL Text-to-Image › a dragon"


def test_strip_click_opens_new_tab_when_settings_differ(tabs):
    _insert_gen(tabs._db, "g1", _sdxl_full(positive_prompt="cat", seed=5))
    tabs.currentWidget().prefill("wan22_i2v", {})  # the current tab is a different folder
    tabs._on_strip_activated("g1")
    assert tabs.count() == 2  # the current tab + a new one for g1
    panel = tabs.currentWidget()
    assert panel._workflow_combo.currentData() == "sdxl_t2i"
    assert panel._param_form.get_values_static()["seed"] == 5


def test_strip_click_does_nothing_when_settings_match(tabs):
    params = _sdxl_full(positive_prompt="cat", seed=5)
    _insert_gen(tabs._db, "g1", params)
    tabs.currentWidget().prefill("sdxl_t2i", params)  # active tab now has g1's settings
    count = tabs.count()
    tabs._on_strip_activated("g1")
    assert tabs.count() == count


def test_strip_click_matching_settings_ignores_random_seed(tabs):
    # The reported bug: a tab generated g1 and still has its seed on Random.
    panel = tabs.currentWidget()
    panel._param_form.set_values({"positive_prompt": "cat"})  # leaves Random checked
    assert panel._param_form.seed_is_random() is True
    _insert_gen(tabs._db, "g1", _sdxl_full(positive_prompt="cat", seed=777))
    count = tabs.count()
    tabs._on_strip_activated("g1")
    assert tabs.count() == count  # same settings folder -> no duplicate


def test_opening_tab_from_a_thumbnail_populates_strip_with_its_folder(tabs):
    _insert_gen(tabs._db, "cat1", _sdxl_full(positive_prompt="cat", seed=1))
    _insert_gen(tabs._db, "cat2", _sdxl_full(positive_prompt="cat", seed=2))
    _insert_gen(tabs._db, "dog1", _sdxl_full(positive_prompt="dog", seed=1))
    tabs.currentWidget().prefill("wan22_i2v", {})  # a different folder so the click opens a new tab
    tabs._on_strip_activated("cat1")
    assert isinstance(tabs.currentWidget(), GenerateConfigPanel)
    assert _strip_ids(tabs) == ["cat2", "cat1"]  # the whole cat folder, newest first


# --- bringing a generation's own tab forward -------------------------------

def test_reveal_config_opens_a_tab_for_a_generation_with_none(tabs):
    _insert_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a heron", seed=4))
    tabs.currentWidget().prefill("wan22_i2v", {})  # the open tab is a different folder

    tabs.reveal_config("g1")

    assert tabs.count() == 2
    assert tabs.currentWidget()._param_form.get_values_static()["positive_prompt"] == "a heron"


def test_reveal_config_brings_forward_a_tab_that_already_has_it(tabs):
    # A queued job's row is clicked while its own tab sits behind another: that
    # tab comes forward rather than a duplicate of it opening.
    params = _sdxl_full(positive_prompt="a heron", seed=4)
    _insert_gen(tabs._db, "g1", params)
    tabs.currentWidget().prefill("sdxl_t2i", params)
    its_tab = tabs.currentWidget()
    tabs._add_subtab()  # some other tab is in front now

    tabs.reveal_config("g1")

    assert tabs.count() == 2  # no third tab
    assert tabs.currentWidget() is its_tab


def test_reveal_config_ignores_a_generation_that_is_gone(tabs):
    count = tabs.count()
    tabs.reveal_config("never-existed")
    assert tabs.count() == count


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


def test_load_selection_opens_a_new_tab_for_a_different_folder(tabs):
    cat = _complete_gen(tabs._db, "cat", _sdxl_full(positive_prompt="cat", seed=1), "cat.png")
    dog = _complete_gen(tabs._db, "dog", _sdxl_full(positive_prompt="dog", seed=1), "dog.png")
    tabs.currentWidget()._preview.show_media = MagicMock()
    tabs.load_selection(cat, [cat, dog])
    count = tabs.count()

    tabs.load_selection(dog, [cat, dog])  # a different settings folder

    assert tabs.count() == count + 1  # forked a new tab rather than clobbering
    assert tabs.current_config_panel()._displayed_row is dog


def test_current_config_panel_is_the_front_tab(tabs):
    first = tabs.currentWidget()
    second = tabs._add_subtab()
    assert tabs.current_config_panel() is second
    tabs.setCurrentIndex(tabs.indexOf(first))
    assert tabs.current_config_panel() is first


def test_show_selection_preview_updates_only_the_current_preview(tabs):
    panel = tabs.currentWidget()
    panel._preview.show_media = MagicMock()
    panel.prefill = MagicMock()

    tabs.show_selection_preview(("x.png", "image"), "g1")

    panel._preview.show_media.assert_called_once_with("x.png", "image")
    panel.prefill.assert_not_called()  # no form change
    assert panel._preview._draggable_id == "g1"  # its preview drags onto combine


def test_show_selection_preview_of_nothing_disarms_the_drag(tabs):
    panel = tabs.currentWidget()
    panel._preview.set_draggable_id("stale")  # a prior selection left it armed

    tabs.show_selection_preview(None, "g1")  # the file is gone: clear the preview

    assert panel._preview._draggable_id is None  # nothing shown, nothing to drag


def test_show_reroll_frame_shows_a_waiting_note_without_a_frame(tabs):
    panel = tabs.currentWidget()
    panel._preview.show_message = MagicMock()
    tabs.show_reroll_frame(None)
    panel._preview.show_message.assert_called_once()
    # Marked live, so the pane can be double-clicked open before the first frame.
    assert panel._preview.show_message.call_args.kwargs == {"live": True}


def test_show_reroll_frame_prefers_a_given_wait_note(tabs):
    # "Waiting for preview…" says nothing about why. When the caller knows what the
    # run is stuck behind, that replaces it.
    panel = tabs.currentWidget()
    panel._preview.show_message = MagicMock()
    tabs.show_reroll_frame(None, "Waiting behind 3 jobs from another app")
    assert panel._preview.show_message.call_args.args[0] == "Waiting behind 3 jobs from another app"


def test_show_reroll_frame_mirrors_a_frame(tabs):
    panel = tabs.currentWidget()
    panel._preview.show_frame = MagicMock()
    tabs.show_reroll_frame(b"frame")
    panel._preview.show_frame.assert_called_once_with(b"frame")


def test_clear_current_preview_clears_the_front_tab(tabs):
    panel = tabs.currentWidget()
    panel._preview.clear = MagicMock()
    tabs.clear_current_preview()
    panel._preview.clear.assert_called_once()


def test_show_result_in_current_tab_keeps_a_prompt_typed_while_it_ran(tabs):
    # A Generate finishing in the front tab lands its result there, but must not
    # wipe a prompt the user has since typed into that same tab's form.
    row = _complete_gen(tabs._db, "g1", _sdxl_full(positive_prompt="a cat", seed=1),
                        "sdxl_g1.png")
    panel = tabs.current_config_panel()
    panel._preview.show_media = MagicMock()
    panel._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    tabs.show_result_in_current_tab(row, [row])

    assert panel._param_form.get_values_static()["positive_prompt"] == "a wizard mid-edit"
    assert panel._displayed_row is row  # the finished result is on display


# --- rename ----------------------------------------------------------------

def test_double_click_renames_config_tab(tabs, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
    panel = tabs._add_subtab()
    idx = tabs.indexOf(panel)
    tabs._rename_subtab(idx)
    assert panel._custom_title == "Renamed"
    assert tabs.tabText(idx) == "Renamed"


def test_rename_cancelled_leaves_title(tabs, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    panel = tabs._add_subtab()
    idx = tabs.indexOf(panel)
    before = panel.title()
    tabs._rename_subtab(idx)
    assert panel._custom_title is None
    assert tabs.tabText(idx) == before


def test_double_clicking_close_does_not_open_rename(tabs, monkeypatch):
    # Double-clicking the ✕ closes a config tab on its first click; the remaining
    # tabs shift left and the completing double-click lands on the neighbor, firing
    # tabBarDoubleClicked. That stray click must not open the rename dialog.
    from PyQt6.QtWidgets import QInputDialog
    tabs._add_subtab()
    tabs._add_subtab()  # three tabs, so a neighbor slides under the cursor
    opened = []
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: opened.append(True) or ("X", True))
    tabs._close_subtab(1)   # first click of the double-click removes the tab at 1
    tabs._rename_subtab(1)  # completing double-click, now over the shifted neighbor
    assert opened == []


# --- session capture / restore ---------------------------------------------

def _config_tab(workflow_name, params=None, seed_is_random=True, title=None):
    return {
        "config": {"workflow_name": workflow_name,
                   "params": params or {}, "seed_is_random": seed_is_random},
        "title": title,
    }


def test_the_run_a_tab_launched_survives_a_restart(tabs, qtbot):
    # A tab's Cancel and progress fill follow the run it started, so which run that
    # was has to come back with the tab — otherwise a restart mid-generation
    # reopens the tab with an idle button over a job still cooking.
    tabs.currentWidget().note_launched("run-77")

    fresh = InfoPaneTabs(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(tabs.capture_state())

    assert fresh._config_panels()[0].launched_run() == "run-77"


def test_a_tab_that_never_generated_claims_no_run(tabs, qtbot):
    fresh = InfoPaneTabs(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(tabs.capture_state())

    assert fresh._config_panels()[0].launched_run() is None


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
    panel = tabs.currentWidget()
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
    panels = tabs._config_panels()
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
    panels = tabs._config_panels()
    assert len(panels) == 1
    assert panels[0]._workflow_combo.currentData() == "wan22_i2v"


def test_restore_state_keeps_the_initial_tab_when_nothing_restorable(tabs):
    tabs.restore_state({})
    tabs.restore_state({"tabs": [_config_tab("gone")]})
    assert len(tabs._config_panels()) == 1  # the initial tab is left in place
    assert tabs.count() == 1


def test_restore_state_tolerates_malformed_blobs(tabs):
    # A corrupt/cross-version state value must not brick startup.
    tabs.restore_state("not a dict")
    tabs.restore_state({"tabs": "not a list"})
    tabs.restore_state({"tabs": ["not a dict", {"config": {"workflow_name": "wan22_i2v"}}]})
    panels = tabs._config_panels()
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


def test_capture_restore_round_trips_config_and_custom_title(tabs, qtbot):
    tabs.currentWidget().prefill("sdxl_t2i", {})  # a plain sdxl tab
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox", "seed": 7})  # current
    tabs._config_panels()[1].set_custom_title("My Fox")
    captured = tabs.capture_state()

    fresh = InfoPaneTabs(tabs._client, tabs._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(captured)

    panels = fresh._config_panels()
    assert [p._workflow_combo.currentData() for p in panels] == ["sdxl_t2i", "wan22_i2v"]
    assert panels[1]._param_form.get_values_static()["seed"] == 7
    # A renamed tab comes back named, not reset to its auto gallery-folder label.
    assert panels[1].custom_title() == "My Fox"
    assert fresh.tabText(fresh.indexOf(panels[1])) == "My Fox"
    assert fresh.currentIndex() == captured["current"]
