import json
from unittest.mock import patch

from origenerator import gallery
from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.main_window import OrigeneratorWindow
from origenerator.workflows import WORKFLOW_REGISTRY


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


def test_reconnects_a_running_reroll_after_restore(qtbot, tmp_path):
    # A re-roll left running by a prior session — owned by no restored tab — is
    # picked back up by the gallery once the window builds. The window's own DB is
    # the same file (tmp_path / "t.db"), so it sees the row inserted here.
    db = Database(tmp_path / "t.db")
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  seed=99, positive_prompt="a cat")
    db.insert_generation(
        prompt_id="rr", workflow_name="sdxl_t2i", workflow_version="v",
        positive_prompt="a cat", seed=99,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation("rr", status="running")

    win = _window(qtbot, tmp_path)

    key = gallery.settings_folder_key(db.get_generation("rr"))
    assert key in win._gallery_view._reroll_jobs


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


def test_restores_active_tab_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("active_tab", 1)  # Gallery
    win = _window(qtbot, tmp_path, state)
    assert win._tabs.currentWidget() is win._gallery_view


def test_restores_gallery_selection_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("gallery_selection", "abc123")
    win = _window(qtbot, tmp_path, state)
    assert win._gallery_view.selected_generation() == "abc123"


def test_close_event_persists_active_tab(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    win = _window(qtbot, tmp_path, AppState(path))
    win._tabs.setCurrentWidget(win._gallery_view)

    win.close()  # fires closeEvent

    assert AppState(path).get("active_tab") == 1


def test_close_event_persists_gallery_selection(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    win = _window(qtbot, tmp_path, AppState(path))
    win._gallery_view.select_generation("xyz")

    win.close()  # fires closeEvent

    assert AppState(path).get("gallery_selection") == "xyz"


def test_default_window_is_not_maximized(qtbot, tmp_path):
    # With no saved state (a first launch), the window opens at its normal size.
    win = _window(qtbot, tmp_path)
    assert not win.isMaximized()


def test_close_event_persists_window_geometry(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    win = _window(qtbot, tmp_path, AppState(path))
    win.showMaximized()

    win.close()  # fires closeEvent

    # Geometry is stored as a base64 string (Qt's opaque saveGeometry blob),
    # which also carries the window's screen and maximized state.
    assert isinstance(AppState(path).get("window_geometry"), str)


def test_reopening_a_maximized_window_reopens_maximized(qtbot, tmp_path):
    # The whole point: close it maximized, and the next launch is maximized —
    # on the same monitor, since the geometry blob records the screen too.
    path = tmp_path / "ui.json"
    first = _window(qtbot, tmp_path, AppState(path))
    first.showMaximized()
    first.close()

    reopened = _window(qtbot, tmp_path, AppState(path))
    assert reopened.isMaximized()


def test_reopening_a_normal_window_stays_normal(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    first = _window(qtbot, tmp_path, AppState(path))
    first.show()
    first.close()

    reopened = _window(qtbot, tmp_path, AppState(path))
    assert not reopened.isMaximized()
