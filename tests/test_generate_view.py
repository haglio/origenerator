import json
from unittest.mock import MagicMock, patch

import pytest

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.generation_config import merge_denormalized
from origenerator.gui.generate_view import GenerateView


@pytest.fixture
def view(qtbot, tmp_path):
    client = ComfyUIClient()
    db = Database(tmp_path / "test.db")
    v = GenerateView(client, db)
    qtbot.addWidget(v)
    return v


def _insert(db, prompt_id, **over):
    fields = dict(
        prompt_id=prompt_id,
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        positive_prompt="",
        negative_prompt="",
        seed=5,
        params_json=json.dumps({"seed": 5}),
        workflow_json="{}",
    )
    fields.update(over)
    db.insert_generation(**fields)


def _strip_ids(view):
    strip = view._strip
    return [strip._list.itemAt(i).widget().prompt_id for i in range(strip._list.count())]


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
    _insert(view._db, "x1")
    view._subtabs.widget(0)._generated_ids = ["x1"]
    view._refresh_strip()
    assert _strip_ids(view) == ["x1"]
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


def test_strip_shows_only_the_active_tabs_generations(view):
    p1 = view._subtabs.widget(0)
    p2 = view._add_subtab()
    _insert(view._db, "a1")
    _insert(view._db, "b1")
    p1._generated_ids = ["a1"]
    p2._generated_ids = ["b1"]
    view._refresh_strip()  # p2 is active
    assert _strip_ids(view) == ["b1"]
    view._subtabs.setCurrentIndex(0)  # switching tabs swaps the strip
    assert _strip_ids(view) == ["a1"]


def test_open_config_adds_and_prefills_subtab(view):
    view.open_config("wan22_i2v", {"positive_prompt": "a fox"})
    assert view._subtabs.count() == 2
    panel = view._subtabs.currentWidget()
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_strip_click_opens_new_subtab_when_settings_differ(view):
    _insert(view._db, "g1", positive_prompt="cat", seed=5)
    # The lone subtab is blank with a random seed, so it never matches g1.
    view._on_strip_activated("g1")
    assert view._subtabs.count() == 2
    panel = view._subtabs.currentWidget()
    assert panel._workflow_combo.currentData() == "sdxl_t2i"
    assert panel._param_form.get_values_static()["seed"] == 5


def test_strip_click_does_nothing_when_settings_match(view):
    _insert(view._db, "g1", positive_prompt="cat", seed=5)
    params = merge_denormalized(view._db.get_generation("g1"))
    view.open_config("sdxl_t2i", params)  # active subtab now mirrors g1
    count = view._subtabs.count()
    view._on_strip_activated("g1")
    assert view._subtabs.count() == count


def test_tab_text_follows_gallery_folder_name(view):
    view.open_config("sdxl_t2i", {"positive_prompt": "a dragon"})
    idx = view._subtabs.currentIndex()
    assert view._subtabs.tabText(idx) == "SDXL Text-to-Image: a dragon"


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
    assert p1._comfy_prompt_id == "comfy-1"           # first is running
    assert "queued" in p2._progress.format().lower()


def test_closing_running_subtab_advances_the_queue(view):
    view._client.submit_job = MagicMock(return_value="comfy-1")
    p1 = view._subtabs.widget(0)
    p2 = view._add_subtab()
    p1._on_generate()  # running
    p2._on_generate()  # queued
    view._close_subtab(view._subtabs.indexOf(p1))
    assert p2._comfy_prompt_id == "comfy-1"           # p2 promoted and started
