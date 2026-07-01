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
    strip = view._strip
    return [strip._list.itemAt(i).widget().prompt_id for i in range(strip._list.count())]


SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "x.png", "subfolder": ""}]}}}


def test_starts_with_one_subtab(view):
    assert view._subtabs.count() == 1


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


def test_closing_last_subtab_empties_the_strip(view):
    _insert_gen(view._db, "x1", _sdxl_full(positive_prompt="cat"))
    view.open_config("sdxl_t2i", _sdxl_full(positive_prompt="cat"))  # seeds the strip with x1
    assert _strip_ids(view) == ["x1"]
    while view._subtabs.count():
        view._close_subtab(0)
    assert _strip_ids(view) == []


def test_close_subtab_removes_and_tears_down_when_multiple(view):
    panel = view._add_subtab()
    assert view._subtabs.count() == 2
    with patch.object(panel, "teardown", wraps=panel.teardown) as spy:
        view._close_subtab(view._subtabs.indexOf(panel))
    spy.assert_called_once()
    assert view._subtabs.count() == 1


def test_active_panel_completion_refreshes_strip(view):
    panel = view._subtabs.currentWidget()
    with patch.object(
        view._strip, "show_generations", wraps=view._strip.show_generations
    ) as spy:
        panel.generation_completed.emit("anything")
    spy.assert_called()


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
