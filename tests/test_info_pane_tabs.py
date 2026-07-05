import json
from unittest.mock import MagicMock, patch

import pytest

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
    """Insert a generation whose params_json reflects its real settings."""
    db.insert_generation(
        prompt_id=prompt_id,
        workflow_name=workflow_name,
        workflow_version="v002",
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


SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "x.png", "subfolder": ""}]}}}


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


# --- a read-only gallery (no client) ---------------------------------------

def test_a_tab_still_shows_without_a_client(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    tabs = InfoPaneTabs(None, db)  # a read-only gallery: nothing to run
    qtbot.addWidget(tabs)
    assert tabs.count() == 1  # a tab still shows, Generate disabled
    assert tabs.widget(0)._generate_btn.isEnabled() is False
    assert not tabs._add_btn.isVisible()


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


def test_strip_keeps_earlier_runs_after_a_settings_change(tabs):
    # The reported bug: changing params and regenerating must NOT wipe the strip.
    panel = tabs.currentWidget()
    panel._client.submit_job = MagicMock(return_value="comfy-A")

    panel._param_form.set_values({"positive_prompt": "cat", "seed": 1})
    panel._on_generate()
    first = panel._client_prompt_id
    panel._client.job_completed.emit(first, SDXL_HISTORY)
    assert _strip_ids(tabs) == [first]

    panel._param_form.set_values({"positive_prompt": "dog", "seed": 2})  # a mod
    panel._on_generate()
    second = panel._client_prompt_id
    panel._client.job_completed.emit(second, SDXL_HISTORY)
    # Both runs stay, newest first — the earlier (now-mismatched) one isn't dropped.
    assert _strip_ids(tabs) == [second, first]


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

    tabs.show_selection_preview(("x.png", "image"))

    panel._preview.show_media.assert_called_once_with("x.png", "image")
    panel.prefill.assert_not_called()  # no form change


def test_show_reroll_frame_shows_a_waiting_note_without_a_frame(tabs):
    panel = tabs.currentWidget()
    panel._preview.show_message = MagicMock()
    tabs.show_reroll_frame(None)
    panel._preview.show_message.assert_called_once()


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


# --- the one-generation-at-a-time queue ------------------------------------

def test_second_generate_is_queued_behind_the_first(tabs):
    tabs._client.submit_job = MagicMock(return_value="comfy-1")
    p1 = tabs.currentWidget()
    p2 = tabs._add_subtab()
    p1._on_generate()
    p2._on_generate()
    assert tabs._client.submit_job.call_count == 1   # only the first reaches ComfyUI
    assert p1._client_prompt_id is not None           # first is running
    assert "queued" in p2._progress.format().lower()


def test_closing_running_config_tab_advances_the_queue(tabs):
    tabs._client.submit_job = MagicMock(return_value="comfy-1")
    p1 = tabs.currentWidget()
    p2 = tabs._add_subtab()
    p1._on_generate()  # running
    p2._on_generate()  # queued
    tabs._close_subtab(tabs.indexOf(p1))
    assert p2._client_prompt_id is not None           # p2 promoted and started


# --- session capture / restore ---------------------------------------------

def _config_tab(workflow_name, params=None, seed_is_random=True, title=None):
    return {
        "config": {"workflow_name": workflow_name,
                   "params": params or {}, "seed_is_random": seed_is_random},
        "title": title,
    }


def test_capture_state_lists_every_tab_and_current(tabs):
    tabs.currentWidget().prefill("sdxl_t2i", {})                  # the initial tab
    tabs.open_config("wan22_i2v", {"positive_prompt": "a fox"})   # index 1, current
    state = tabs.capture_state()
    workflows = [tab["config"]["workflow_name"] for tab in state["tabs"]]
    assert workflows == ["sdxl_t2i", "wan22_i2v"]
    assert state["current"] == 1


def test_capture_state_records_each_tab_active_prompt_id(tabs):
    panel = tabs.currentWidget()
    panel._client.submit_job = MagicMock(return_value="x")
    panel._on_generate()
    state = tabs.capture_state()
    assert state["tabs"][0]["active_prompt_id"] == panel._client_prompt_id


def test_capture_state_active_prompt_id_is_none_when_idle(tabs):
    state = tabs.capture_state()
    assert state["tabs"][0]["active_prompt_id"] is None


def _running_row(db, prompt_id="run-1"):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    payload = wf.build_api_payload(wf.default_params())
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v",
        params_json=json.dumps(_sdxl_full()), workflow_json=json.dumps(payload),
    )
    db.update_generation(prompt_id, status="running")


def _restore_tab_state(active_prompt_id):
    return {"tabs": [{
        "config": {"workflow_name": "sdxl_t2i", "params": _sdxl_full(),
                   "seed_is_random": False},
        "title": None, "active_prompt_id": active_prompt_id,
    }], "current": 0}


def test_restore_reconnects_a_still_running_tab(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    _running_row(db, "run-1")
    client = ComfyUIClient()
    tabs = InfoPaneTabs(client, db)
    qtbot.addWidget(tabs)

    tabs.restore_state(_restore_tab_state("run-1"))

    panel = tabs._config_panels()[0]
    assert panel.active_prompt_id() == "run-1"  # reconnected to the running job
    assert panel._cancel_btn.isEnabled() is True
    # its completion now flows back into the restored tab
    client.job_completed.emit("run-1", SDXL_HISTORY)
    assert db.get_generation("run-1")["status"] == "completed"


def test_restore_does_not_reconnect_a_finished_job(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    _running_row(db, "done")
    db.update_generation("done", status="completed")
    client = ComfyUIClient()
    tabs = InfoPaneTabs(client, db)
    qtbot.addWidget(tabs)

    tabs.restore_state(_restore_tab_state("done"))

    assert tabs._config_panels()[0].active_prompt_id() is None


def test_active_prompt_ids_collects_in_flight_tabs(tabs):
    p0 = tabs.currentWidget()
    p0._client.submit_job = MagicMock(return_value="x")
    tabs._add_subtab()  # a second, idle tab
    p0._on_generate()
    assert tabs.active_prompt_ids() == {p0._client_prompt_id}


# --- in-flight items: the cards the gallery's Recents shelf reads from here ---

def test_in_flight_items_is_empty_when_nothing_is_generating(tabs):
    assert tabs.in_flight_items() == []


def test_in_flight_items_reports_a_running_job(tabs):
    tabs._client.submit_job = MagicMock(return_value="x")
    panel = tabs.currentWidget()
    panel._on_generate()
    items = tabs.in_flight_items()
    assert len(items) == 1
    assert items[0].key == panel.active_prompt_id()


def test_in_flight_items_carry_the_tab_media_type(tabs):
    # The Recents card badges a job image-or-video from its tab's workflow; the
    # config tab here runs SDXL, an image pipeline.
    tabs._client.submit_job = MagicMock(return_value="x")
    panel = tabs.currentWidget()
    panel._on_generate()
    assert tabs.in_flight_items()[0].media_type == "image"


def test_in_flight_items_includes_a_tab_queued_behind_a_running_one(tabs):
    tabs._client.submit_job = MagicMock(return_value="x")
    p1 = tabs.currentWidget()
    p2 = tabs._add_subtab()
    p1._param_form.set_values({"seed": 1})
    p2._param_form.set_values({"seed": 2})
    p1._on_generate()   # running
    p2._on_generate()   # queued behind it — no DB row, but still in flight
    assert len(tabs.in_flight_items()) == 2


def test_generation_started_surfaces_from_the_initial_tab(tabs):
    # The tab strip re-emits each tab's generation_started so the gallery can react
    # to a job launched from any tab — here the initial one.
    tabs._client.submit_job = MagicMock(return_value="x")
    started = []
    tabs.generation_started.connect(started.append)
    panel = tabs.currentWidget()

    panel._on_generate()

    assert started == [panel.active_prompt_id()]


def test_generation_started_surfaces_from_a_forked_tab(tabs):
    # A tab forked after construction must also have its generation_started wired,
    # like title_changed — so a job from any tab reaches the gallery.
    tabs._client.submit_job = MagicMock(return_value="x")
    started = []
    tabs.generation_started.connect(started.append)
    forked = tabs.open_config("sdxl_t2i", _sdxl_full(positive_prompt="a fox"))

    forked._on_generate()

    assert started == [forked.active_prompt_id()]


def test_revealing_an_item_selects_its_config_tab(tabs):
    tabs._client.submit_job = MagicMock(return_value="x")
    first = tabs.currentWidget()
    tabs._add_subtab()  # a second config tab is now current
    assert tabs.currentWidget() is not first
    first._on_generate()  # the first tab is the one generating
    tabs.in_flight_items()[0].reveal()
    assert tabs.currentWidget() is first  # reveal jumped to the generating tab


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
