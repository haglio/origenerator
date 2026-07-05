import json

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


def test_reuse_requested_opens_a_config_tab(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    tabs = win._gallery_view._info_tabs
    assert tabs.count() == 1  # only the Inspect tab to start

    win._gallery_view.reuse_requested.emit("wan22_i2v", {"positive_prompt": "hi"})

    assert tabs.count() == 2
    panel = tabs.currentWidget()
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "hi"


def test_restores_config_tabs_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("generate_tabs", {"tabs": [
        {"config": {"workflow_name": "sdxl_t2i", "params": {}, "seed_is_random": True}},
        {"config": {"workflow_name": "wan22_i2v", "params": {}, "seed_is_random": True}},
    ], "current": 2})
    win = _window(qtbot, tmp_path, state)

    panels = win._gallery_view._info_tabs._config_panels()
    assert len(panels) == 2
    assert panels[1]._workflow_combo.currentData() == "wan22_i2v"


def test_restores_the_global_osr2_toggle_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("osr2_enabled", True)
    win = _window(qtbot, tmp_path, state)
    assert win._gallery_view.osr2_enabled() is True


def test_persists_the_global_osr2_toggle_on_close(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    win = _window(qtbot, tmp_path, state)
    win._gallery_view.set_osr2_enabled(True)

    win.close()  # closeEvent persists the session
    assert state.get("osr2_enabled") is True


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
    win._gallery_view._info_tabs.open_config("wan22_i2v", {"positive_prompt": "x"})
    win._gallery_view.select_folder("image/sdxl_t2i")

    win.close()  # fires closeEvent

    reloaded = AppState(path)
    tabs = reloaded.get("generate_tabs")["tabs"]
    # Every tab is captured now (no special/permanent tab): the initial editable
    # tab plus the one just opened.
    assert [t["config"]["workflow_name"] for t in tabs] == ["sdxl_t2i", "wan22_i2v"]
    assert reloaded.get("gallery_folder") == "image/sdxl_t2i"


def test_restores_gallery_selection_from_app_state(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("gallery_selection", "abc123")
    win = _window(qtbot, tmp_path, state)
    assert win._gallery_view.selected_generation() == "abc123"


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


def test_window_still_tiles_with_a_config_tab_open(qtbot, tmp_path):
    # A config tab's preview-over-form column is wider than the Inspect page, so it
    # governs the info pane's floor. Even with one open, the window must still fit a
    # narrow tiling slot — its form scrolls rather than widening the window.
    win = _window(qtbot, tmp_path)
    win._gallery_view._info_tabs.open_config("wan22_i2v", {"positive_prompt": "x"})
    effective_min_width = max(win.minimumWidth(), win.minimumSizeHint().width())
    assert effective_min_width <= 704


def test_generate_inflight_shows_on_recents_and_reveals_its_folder(qtbot, tmp_path):
    # A tab's Generate launches a re-roll of its settings folder; that in-flight
    # generation shows as a card on Recents, and clicking the card opens the folder
    # it runs in (where its live tile shows), just like any re-roll's card.
    win = _window(qtbot, tmp_path)
    gv = win._gallery_view
    tabs = gv._info_tabs
    tabs._client.submit_job = lambda payload, prompt_id: prompt_id
    tabs._client.fetch_history = lambda prompt_id: {}  # reconcile finds nothing done
    panel = tabs.current_config_panel()
    panel._param_form.set_values({"seed": 2, "positive_prompt": "a dog"})
    panel._on_generate()               # emits generate_requested -> a folder re-roll
    (folder_key,) = list(gv._reroll_jobs)
    pid = gv._reroll_jobs[folder_key].prompt_id

    gv._tree.setCurrentItem(gv._recents_item)
    assert pid in gv._inflight_cards   # the running generation shows as a card

    gv._on_inflight_clicked(pid)       # click that card
    assert gv._selected_folder_key() == folder_key  # reveal opened the re-roll's folder


def test_running_generate_job_shows_on_recents_after_restart(qtbot, tmp_path):
    # The reported bug: a generation left running by a prior session (here an i2v
    # video), with the gallery restored onto Recents. It must show as an in-flight
    # card — the shelf reads the database's running rows, so a card appears whether
    # or not the re-roll controller has re-adopted the job this instant.
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
         "title": None},
    ], "current": 1})
    state.set("gallery_folder", "__recents__")
    win = _window(qtbot, tmp_path, state)

    gv = win._gallery_view
    gv.refresh()
    gv._tree.setCurrentItem(gv._recents_item)
    assert "vid_run" in gv._inflight_cards


def _seed_combine_db(tmp_path):
    """Put a completed image + i2v video in the window's DB so the combine slots
    can be filled from persisted ids."""
    db = Database(tmp_path / "t.db")
    db.insert_generation(prompt_id="img", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="a dog", seed=1,
                         params_json=json.dumps({"positive_prompt": "a dog", "seed": 1}),
                         workflow_json="{}")
    db.update_generation("img", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_img.png"}]))
    db.insert_generation(prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v",
                         positive_prompt="dance", seed=42,
                         params_json=json.dumps(dict(
                             WORKFLOW_REGISTRY["wan22_i2v"].default_params(), seed=42)),
                         workflow_json="{}")
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4"}]))


def test_close_event_persists_combine_selection(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    _seed_combine_db(tmp_path)
    win = _window(qtbot, tmp_path, AppState(path))
    win._gallery_view._combine.image_slot.set_item("img")
    win._gallery_view._combine.video_slot.set_item("vid")

    win.close()

    assert AppState(path).get("gallery_combine") == ["img", "vid"]


def test_restores_combine_selection_from_app_state(qtbot, tmp_path):
    _seed_combine_db(tmp_path)
    state = AppState(tmp_path / "ui.json")
    state.set("gallery_combine", ["img", "vid"])

    win = _window(qtbot, tmp_path, state)

    assert win._gallery_view._combine.image_slot.current_id() == "img"
    assert win._gallery_view._combine.video_slot.current_id() == "vid"


def test_combine_selection_survives_close_and_reopen(qtbot, tmp_path):
    # The end-to-end round trip: pick a pair, close, and a fresh window restores it.
    _seed_combine_db(tmp_path)
    path = tmp_path / "ui.json"
    first = _window(qtbot, tmp_path, AppState(path))
    first._gallery_view._combine.image_slot.set_item("img")
    first._gallery_view._combine.video_slot.set_item("vid")
    first.close()

    reopened = _window(qtbot, tmp_path, AppState(path))

    assert reopened._gallery_view._combine.image_slot.current_id() == "img"
    assert reopened._gallery_view._combine.video_slot.current_id() == "vid"
