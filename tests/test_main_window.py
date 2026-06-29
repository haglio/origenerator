from unittest.mock import patch

from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.main_window import OrigeneratorWindow


def _window(qtbot, tmp_path, app_state=None):
    win = OrigeneratorWindow(
        ComfyUIClient(),
        Database(tmp_path / "t.db"),
        app_state or AppState(tmp_path / "ui.json"),
    )
    qtbot.addWidget(win)
    return win


def test_reuse_requested_opens_config_and_switches_tab(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)

    with patch.object(
        win._generate_view, "open_config", wraps=win._generate_view.open_config
    ) as spy:
        win._gallery_view.reuse_requested.emit("wan22_i2v", {"positive_prompt": "hi"})

    spy.assert_called_once_with("wan22_i2v", {"positive_prompt": "hi"})
    assert win._tabs.currentWidget() is win._generate_view


def test_restores_generate_tabs_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("generate_tabs", {"tabs": [
        {"config": {"workflow_name": "sdxl_t2i", "params": {}, "seed_is_random": True}},
        {"config": {"workflow_name": "wan22_i2v", "params": {}, "seed_is_random": True}},
    ], "current": 1})
    win = _window(qtbot, tmp_path, state)

    gv = win._generate_view
    assert gv._subtabs.count() == 2
    assert gv._subtabs.widget(1)._workflow_combo.currentData() == "wan22_i2v"


def test_restores_gallery_folder_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("gallery_folder", "image/sdxl_t2i")
    win = _window(qtbot, tmp_path, state)

    assert win._gallery_view.selected_folder() == "image/sdxl_t2i"


def test_close_event_persists_session(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    win = _window(qtbot, tmp_path, AppState(path))
    win._generate_view.open_config("wan22_i2v", {"positive_prompt": "x"})
    win._gallery_view.select_folder("image/sdxl_t2i")

    win.close()  # fires closeEvent

    reloaded = AppState(path)
    tabs = reloaded.get("generate_tabs")["tabs"]
    assert [t["config"]["workflow_name"] for t in tabs] == ["sdxl_t2i", "wan22_i2v"]
    assert reloaded.get("gallery_folder") == "image/sdxl_t2i"


def test_replay_requested_submits_and_switches_tab(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)

    row = {"workflow_name": "x", "workflow_json": "{}"}
    overrides = {"positive": "p", "negative": "", "seed": None, "input_image": None}
    with patch.object(
        win._generate_view, "submit_replay", wraps=win._generate_view.submit_replay
    ) as spy:
        win._gallery_view.replay_requested.emit(row, overrides)

    spy.assert_called_once_with(row, overrides)
    assert win._tabs.currentWidget() is win._generate_view


def test_restores_active_tab_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("active_tab", 1)  # Gallery
    win = _window(qtbot, tmp_path, state)
    assert win._tabs.currentWidget() is win._gallery_view


def test_close_event_persists_active_tab(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    win = _window(qtbot, tmp_path, AppState(path))
    win._tabs.setCurrentWidget(win._gallery_view)

    win.close()  # fires closeEvent

    assert AppState(path).get("active_tab") == 1
