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


def test_reconnects_a_running_i2v_reroll_by_its_frame_config(qtbot, tmp_path):
    # An i2v re-roll keys to its folder by the *config* of its start frame. The
    # reconnect must resolve that from the DB (the first tree rebuild, which would
    # populate the image rows, hasn't run yet), so the adopted job lands under the
    # same key the gallery tree will later give it.
    db = Database(tmp_path / "t.db")
    img_params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                      seed=1, positive_prompt="a face")
    db.insert_generation(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version="v",
        positive_prompt="a face", seed=1,
        params_json=json.dumps(img_params), workflow_json="{}",
    )
    db.update_generation(
        "img", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_img.png"}]),
    )
    vid_params = dict(WORKFLOW_REGISTRY["wan22_i2v"].default_params(),
                      seed=7, positive_prompt="", input_image="sdxl_t2i_img.png [output]")
    db.insert_generation(
        prompt_id="rr", workflow_name="wan22_i2v", workflow_version="v",
        positive_prompt="", seed=7,
        params_json=json.dumps(vid_params), workflow_json="{}",
    )
    db.update_generation("rr", status="running")

    win = _window(qtbot, tmp_path)

    index = gallery.build_image_config_index([db.get_generation("img")])
    key = gallery.settings_folder_key(db.get_generation("rr"), index)
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


def test_window_can_shrink_to_tile_into_a_monitor_half(qtbot, tmp_path):
    """A tiling window manager snaps windows into fractional slots — a third of a
    2560px monitor (~853px) or a half of a 1440px portrait monitor (~720px). The
    window, frame included (~+16px), must fit the smallest of those, so its
    effective minimum width has to stay under ~704px. Guards against a large
    minimum — explicit or content-driven (a non-wrapping label, a combo sized to
    its longest item) — that makes the window refuse to fit and breaks
    monitor-to-monitor tiling."""
    win = _window(qtbot, tmp_path)
    effective_min_width = max(win.minimumWidth(), win.minimumSizeHint().width())
    assert effective_min_width <= 704


def test_generate_inflight_shows_on_recents_and_reveals_its_subtab(qtbot, tmp_path):
    # The gallery's Recents shelf shows a running Generate-tab job, and clicking
    # its card brings the Generate tab forward on that job's own subtab.
    win = _window(qtbot, tmp_path)
    win._generate_view._client.submit_job = lambda payload, prompt_id: prompt_id
    gen = win._generate_view
    first = gen._subtabs.widget(0)
    first._on_generate()               # the first subtab runs a job
    pid = first.active_prompt_id()
    gen._add_subtab()                  # a second subtab is now current
    assert gen._subtabs.currentWidget() is not first

    gv = win._gallery_view
    gv.refresh()                       # the gallery reads the tabs' in-flight jobs
    gv._tree.setCurrentItem(gv._recents_item)
    assert pid in gv._inflight_cards   # the Generate job shows as an in-flight card

    win._tabs.setCurrentWidget(gv)     # sit on the Gallery tab
    gv._on_inflight_clicked(pid)       # click that card
    assert win._tabs.currentWidget() is win._generate_view   # brought Generate forward
    assert gen._subtabs.currentWidget() is first             # on the generating subtab


def test_running_generate_job_shows_on_recents_after_restart(qtbot, tmp_path):
    # The reported bug: a Generate tab's job left running by a prior session (here an
    # i2v video), with the gallery restored onto Recents. It must show as an
    # in-flight card — the shelf reads the database's running rows, so a card
    # appears whether or not the reconnected tab is tracking the job this instant.
    db = Database(tmp_path / "t.db")
    vid_params = dict(WORKFLOW_REGISTRY["wan22_i2v"].default_params(),
                      seed=7, positive_prompt="x", input_image="img.png")
    db.insert_generation(prompt_id="vid_run", workflow_name="wan22_i2v",
                         workflow_version="v", positive_prompt="x", seed=7,
                         params_json=json.dumps(vid_params),
                         workflow_json=json.dumps({"1": {"inputs": {}}}))
    db.update_generation("vid_run", status="running")
    state = AppState(tmp_path / "ui.json")
    state.set("generate_tabs", {"tabs": [
        {"config": {"workflow_name": "wan22_i2v", "params": vid_params, "seed_is_random": True},
         "title": None, "active_prompt_id": "vid_run"},
    ], "current": 0})
    state.set("gallery_folder", "__recents__")
    win = _window(qtbot, tmp_path, state)

    gv = win._gallery_view
    gv.refresh()
    gv._tree.setCurrentItem(gv._recents_item)
    assert "vid_run" in gv._inflight_cards
