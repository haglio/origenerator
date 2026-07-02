import json
from unittest.mock import MagicMock, patch

import pytest

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generate_view import GenerateView
from origenerator.workflows import WORKFLOW_REGISTRY


@pytest.fixture
def view(qtbot, tmp_path):
    client = ComfyUIClient()
    db = Database(tmp_path / "test.db")
    v = GenerateView(client, db)
    qtbot.addWidget(v)
    return v


def _sdxl_full(**over):
    """A full sdxl param set, as a real generation would store it."""
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params())
    params.update(over)
    return params


def _insert_gen(db, prompt_id, params):
    """Insert a generation whose params_json reflects its real settings."""
    db.insert_generation(
        prompt_id=prompt_id,
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        positive_prompt=params.get("positive_prompt", ""),
        negative_prompt=params.get("negative_prompt", ""),
        seed=params.get("seed"),
        params_json=json.dumps(params),
        workflow_json="{}",
    )


def _strip_ids(view):
    strip = view._subtabs.currentWidget()._strip
    return [strip._list.itemAt(i).widget().prompt_id for i in range(strip._list.count())]


def _has_ancestor(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


def test_thumbnail_strip_sits_within_the_tabbed_content(view):
    # The strip lives inside the tab's content, so the tab row spans it just like
    # the settings and preview panes — it isn't a sibling of the tab bar.
    panel = view._subtabs.currentWidget()
    assert _has_ancestor(panel._strip, view._subtabs)


SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "x.png", "subfolder": ""}]}}}


def test_starts_with_one_subtab(view):
    assert view._subtabs.count() == 1


def test_subtabs_use_the_eliding_tab_bar(view):
    # The subtab row caps and elides long titles and keeps every tab on screen.
    from origenerator.gui.eliding_tab_bar import ElidingTabBar
    assert isinstance(view._subtabs.tabBar(), ElidingTabBar)


def test_subtabs_keep_their_close_button_with_the_eliding_bar(view):
    # Installing a custom bar must precede setTabsClosable, or the per-tab close
    # button silently vanishes — this guards that ordering.
    from PyQt6.QtWidgets import QTabBar
    bar = view._subtabs.tabBar()
    close_btn = (bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
                 or bar.tabButton(0, QTabBar.ButtonPosition.LeftSide))
    assert close_btn is not None


def test_add_subtab_increases_count_and_focuses_new(view):
    view._add_subtab()
    assert view._subtabs.count() == 2
    assert view._subtabs.currentIndex() == 1


def test_closing_last_subtab_shows_empty_state(view):
    view._close_subtab(0)
    assert view._subtabs.count() == 0
    assert view._stack.currentWidget() is view._empty_state


def test_empty_state_new_tab_button_adds_a_subtab(view):
    view._close_subtab(0)  # now empty
    view._new_tab_btn.click()
    assert view._subtabs.count() == 1
    assert view._stack.currentWidget() is view._subtabs


def test_open_config_seeds_the_active_panel_strip(view):
    # Opening a tab from a settings folder seeds that tab's own strip with it.
    _insert_gen(view._db, "x1", _sdxl_full(positive_prompt="cat"))
    view.open_config("sdxl_t2i", _sdxl_full(positive_prompt="cat"))
    assert _strip_ids(view) == ["x1"]


def test_close_subtab_removes_and_tears_down_when_multiple(view):
    panel = view._add_subtab()
    assert view._subtabs.count() == 2
    with patch.object(panel, "teardown", wraps=panel.teardown) as spy:
        view._close_subtab(view._subtabs.indexOf(panel))
    spy.assert_called_once()
    assert view._subtabs.count() == 1


def test_strip_keeps_earlier_runs_after_a_settings_change(view):
    # The reported bug: changing params and regenerating must NOT wipe the strip.
    panel = view._subtabs.currentWidget()
    panel._client.submit_job = MagicMock(return_value="comfy-A")

    panel._param_form.set_values({"positive_prompt": "cat", "seed": 1})
    panel._on_generate()
    first = panel._client_prompt_id
    panel._client.job_completed.emit(first, SDXL_HISTORY)
    assert _strip_ids(view) == [first]

    panel._param_form.set_values({"positive_prompt": "dog", "seed": 2})  # a mod
    panel._on_generate()
    second = panel._client_prompt_id
    panel._client.job_completed.emit(second, SDXL_HISTORY)
    # Both runs stay, newest first — the earlier (now-mismatched) one isn't dropped.
    assert _strip_ids(view) == [second, first]


def test_open_config_adds_and_prefills_subtab(view):
    view.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    assert view._subtabs.count() == 2
    panel = view._subtabs.currentWidget()
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_strip_click_opens_new_subtab_when_settings_differ(view):
    _insert_gen(view._db, "g1", _sdxl_full(positive_prompt="cat", seed=5))
    # The lone blank subtab (no prompt) is a different settings folder than g1.
    view._on_strip_activated("g1")
    assert view._subtabs.count() == 2
    panel = view._subtabs.currentWidget()
    assert panel._workflow_combo.currentData() == "sdxl_t2i"
    assert panel._param_form.get_values_static()["seed"] == 5


def test_strip_click_does_nothing_when_settings_match(view):
    params = _sdxl_full(positive_prompt="cat", seed=5)
    _insert_gen(view._db, "g1", params)
    view.open_config("sdxl_t2i", params)  # active subtab now has g1's settings
    count = view._subtabs.count()
    view._on_strip_activated("g1")
    assert view._subtabs.count() == count


def test_strip_click_matching_settings_ignores_random_seed(view):
    # The reported bug: a tab generated g1 and still has its seed on Random.
    panel = view._subtabs.currentWidget()
    panel._param_form.set_values({"positive_prompt": "cat"})  # leaves Random checked
    assert panel._param_form.seed_is_random() is True
    _insert_gen(view._db, "g1", _sdxl_full(positive_prompt="cat", seed=777))
    count = view._subtabs.count()
    view._on_strip_activated("g1")
    assert view._subtabs.count() == count  # same settings folder -> no duplicate


def test_opening_tab_from_a_thumbnail_populates_strip_with_its_folder(view):
    _insert_gen(view._db, "cat1", _sdxl_full(positive_prompt="cat", seed=1))
    _insert_gen(view._db, "cat2", _sdxl_full(positive_prompt="cat", seed=2))
    _insert_gen(view._db, "dog1", _sdxl_full(positive_prompt="dog", seed=1))
    view._on_strip_activated("cat1")  # different folder than the blank tab -> new tab
    assert view._subtabs.count() == 2
    assert _strip_ids(view) == ["cat2", "cat1"]  # the whole cat folder, newest first


def test_tab_text_follows_gallery_folder_name(view):
    view.open_config("sdxl_t2i", {"positive_prompt": "a dragon"})
    idx = view._subtabs.currentIndex()
    assert view._subtabs.tabText(idx) == "SDXL Text-to-Image › a dragon"


def test_double_click_renames_tab(view, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
    idx = view._subtabs.currentIndex()
    panel = view._subtabs.widget(idx)
    view._rename_subtab(idx)
    assert panel._custom_title == "Renamed"
    assert view._subtabs.tabText(idx) == "Renamed"


def test_rename_cancelled_leaves_title(view, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    idx = view._subtabs.currentIndex()
    panel = view._subtabs.widget(idx)
    before = panel.title()
    view._rename_subtab(idx)
    assert panel._custom_title is None
    assert view._subtabs.tabText(idx) == before


def test_double_clicking_close_does_not_open_rename(view, monkeypatch):
    # Double-clicking the ✕ closes a tab on its first click; the remaining tabs
    # shift left and the completing double-click lands on the neighbor, firing
    # tabBarDoubleClicked. That stray click must not open the rename dialog.
    from PyQt6.QtWidgets import QInputDialog
    view._add_subtab()  # a neighbor to slide under the cursor after the close
    opened = []
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: opened.append(True) or ("X", True))
    view._close_subtab(0)   # first click of the double-click removes tab 0
    view._rename_subtab(0)  # completing double-click, now over the shifted neighbor
    assert opened == []


def test_second_generate_is_queued_behind_the_first(view):
    view._client.submit_job = MagicMock(return_value="comfy-1")
    p1 = view._subtabs.widget(0)
    p2 = view._add_subtab()
    p1._on_generate()
    p2._on_generate()
    assert view._client.submit_job.call_count == 1   # only the first reaches ComfyUI
    assert p1._client_prompt_id is not None           # first is running
    assert "queued" in p2._progress.format().lower()


def test_closing_running_subtab_advances_the_queue(view):
    view._client.submit_job = MagicMock(return_value="comfy-1")
    p1 = view._subtabs.widget(0)
    p2 = view._add_subtab()
    p1._on_generate()  # running
    p2._on_generate()  # queued
    view._close_subtab(view._subtabs.indexOf(p1))
    assert p2._client_prompt_id is not None           # p2 promoted and started


# --- session capture / restore ---------------------------------------------

def _config_tab(workflow_name, params=None, seed_is_random=True, title=None):
    return {
        "config": {"workflow_name": workflow_name,
                   "params": params or {}, "seed_is_random": seed_is_random},
        "title": title,
    }


def test_capture_state_lists_every_open_tab_and_current(view):
    view.open_config("wan22_i2v", {"positive_prompt": "a fox"})  # now current
    state = view.capture_state()
    workflows = [tab["config"]["workflow_name"] for tab in state["tabs"]]
    assert workflows == ["sdxl_t2i", "wan22_i2v"]
    assert state["current"] == 1


def test_capture_state_records_each_tab_active_prompt_id(view):
    panel = view._subtabs.currentWidget()
    panel._client.submit_job = MagicMock(return_value="x")
    panel._on_generate()
    state = view.capture_state()
    assert state["tabs"][0]["active_prompt_id"] == panel._client_prompt_id


def test_capture_state_active_prompt_id_is_none_when_idle(view):
    state = view.capture_state()
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
    view = GenerateView(client, db)
    qtbot.addWidget(view)

    view.restore_state(_restore_tab_state("run-1"))

    panel = view._subtabs.widget(0)
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
    view = GenerateView(client, db)
    qtbot.addWidget(view)

    view.restore_state(_restore_tab_state("done"))

    assert view._subtabs.widget(0).active_prompt_id() is None


def test_active_prompt_ids_collects_in_flight_tabs(view):
    p0 = view._subtabs.widget(0)
    p0._client.submit_job = MagicMock(return_value="x")
    view._add_subtab()  # a second, idle tab
    p0._on_generate()
    assert view.active_prompt_ids() == {p0._client_prompt_id}


def test_restore_state_rebuilds_tabs_replacing_default(view):
    state = {"tabs": [
        _config_tab("wan22_i2v", {"positive_prompt": "a fox"}),
        _config_tab("sdxl_t2i", {"seed": 99}, seed_is_random=False),
    ], "current": 1}
    view.restore_state(state)
    assert view._subtabs.count() == 2  # the lone default tab was replaced
    p0, p1 = view._subtabs.widget(0), view._subtabs.widget(1)
    assert p0._workflow_combo.currentData() == "wan22_i2v"
    assert p0._param_form.get_values_static()["positive_prompt"] == "a fox"
    assert p1._workflow_combo.currentData() == "sdxl_t2i"
    assert p1._param_form.get_values_static()["seed"] == 99
    assert view._subtabs.currentIndex() == 1


def test_restore_state_skips_unknown_workflows(view):
    view.restore_state({"tabs": [
        _config_tab("deleted_wf"), _config_tab("wan22_i2v"),
    ]})
    assert view._subtabs.count() == 1
    assert view._subtabs.widget(0)._workflow_combo.currentData() == "wan22_i2v"


def test_restore_state_keeps_default_when_nothing_restorable(view):
    view.restore_state({})
    view.restore_state({"tabs": [_config_tab("gone")]})
    assert view._subtabs.count() == 1
    assert view._subtabs.widget(0)._workflow_combo.currentData() == "sdxl_t2i"


def test_restore_state_tolerates_malformed_blobs(view):
    # A corrupt/cross-version state value must not brick startup.
    view.restore_state("not a dict")
    view.restore_state({"tabs": "not a list"})
    view.restore_state({"tabs": ["not a dict", {"config": {"workflow_name": "wan22_i2v"}}]})
    assert view._subtabs.count() == 1  # only the one valid entry survived
    assert view._subtabs.widget(0)._workflow_combo.currentData() == "wan22_i2v"


def test_capture_restore_round_trips_config_and_custom_title(view, qtbot):
    view.open_config("wan22_i2v", {"positive_prompt": "a fox", "seed": 7})
    view._subtabs.widget(1).set_custom_title("My Fox")
    captured = view.capture_state()

    fresh = GenerateView(view._client, view._db)
    qtbot.addWidget(fresh)
    fresh.restore_state(captured)

    assert [fresh._subtabs.widget(i)._workflow_combo.currentData()
            for i in range(fresh._subtabs.count())] == ["sdxl_t2i", "wan22_i2v"]
    assert fresh._subtabs.widget(1)._param_form.get_values_static()["seed"] == 7
    # A renamed tab comes back named, not reset to its auto gallery-folder label.
    assert fresh._subtabs.widget(1).custom_title() == "My Fox"
    assert fresh._subtabs.tabText(1) == "My Fox"
    assert fresh._subtabs.currentIndex() == captured["current"]
