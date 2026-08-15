import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut

from origenerator import gallery
from origenerator.app_state import AppState
from origenerator.branch_session import ENV_FLAG
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


def _quit_shortcut(win):
    seq = QKeySequence("Ctrl+Alt+Q")
    for shortcut in win.findChildren(QShortcut):
        if shortcut.key() == seq:
            return shortcut
    raise AssertionError("window has no Ctrl+Alt+Q shortcut")


def test_ctrl_alt_q_quits_persisting_the_session(qtbot, tmp_path):
    # The quit shortcut goes through close(), so it saves the session like any close.
    path = tmp_path / "ui.json"
    win = _window(qtbot, tmp_path, AppState(path))
    win._gallery_view.select_generation("xyz")

    _quit_shortcut(win).activated.emit()  # what pressing Ctrl+Alt+Q fires

    assert AppState(path).get("gallery_selection") == "xyz"


def test_quit_shortcut_fires_from_anywhere_in_the_app(qtbot, tmp_path):
    # Application-scoped, so it triggers regardless of which widget holds focus.
    win = _window(qtbot, tmp_path)
    assert _quit_shortcut(win).context() == Qt.ShortcutContext.ApplicationShortcut


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


def test_restores_the_audio_switch_from_app_state(qtbot, tmp_path):
    # Left on, the audio bed comes back on at the next launch — the same standing
    # preference the OSR2 and experiments switches are.
    state = AppState(tmp_path / "ui.json")
    state.set("audio_enabled", True)
    win = _window(qtbot, tmp_path, state)
    assert win._gallery_view.audio_enabled() is True


def test_persists_the_audio_switch_on_close(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    win = _window(qtbot, tmp_path, state)
    win._gallery_view.set_audio_enabled(True)

    win.close()  # closeEvent persists the session
    assert state.get("audio_enabled") is True


def test_restores_the_experiments_switch_from_app_state(qtbot, tmp_path):
    # The background experimenter resumes across launches — "spend the time I'm
    # not here" is a standing preference, not a per-session one.
    state = AppState(tmp_path / "ui.json")
    state.set("experiments_enabled", True)
    win = _window(qtbot, tmp_path, state)
    assert win._gallery_view.experiments_enabled() is True


def test_persists_the_experiments_switch_on_close(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    win = _window(qtbot, tmp_path, state)
    win._gallery_view.set_experiments_enabled(True)

    win.close()  # closeEvent persists the session
    assert state.get("experiments_enabled") is True


class _QueueSpyClient(ComfyUIClient):
    """A real client whose queue operations are recorded instead of sent."""

    def __init__(self, running=()):
        super().__init__()
        self.running = set(running)
        self.canceled = []
        self.submitted = []
        self.interrupts = 0

    def fetch_running(self):
        return set(self.running)

    def cancel_prompt(self, prompt_id):
        self.canceled.append(prompt_id)

    def interrupt(self):
        self.interrupts += 1

    def submit_job(self, payload, prompt_id):
        self.submitted.append(prompt_id)
        return prompt_id


def _completed_image(db, prompt_id="g-1", prompt="a cat", seed=1):
    """One finished generation for the policy to build experiments on."""
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt=prompt, seed=seed,
        params_json=json.dumps(dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                                    positive_prompt=prompt, seed=seed)),
        workflow_json="{}",
    )
    db.update_generation(
        prompt_id, status="completed",
        output_files=json.dumps([{"filename": f"{prompt_id}.png", "subfolder": ""}]),
    )


def test_closing_hands_comfyui_the_experiments_to_run_while_away(qtbot, tmp_path):
    # The switch is a standing "spend the time I'm not here": closing is what
    # queues the batch, because ComfyUI outlives the app and works through it.
    db = Database(tmp_path / "t.db")
    _completed_image(db)
    client = _QueueSpyClient()
    win = OrigeneratorWindow(client, db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(win)
    win._gallery_view.set_experiments_enabled(True)
    assert client.submitted == []  # nothing while the app is open

    win.close()

    queued = [r for r in db.list_generations() if r.get("source") == "experiment"]
    assert client.submitted
    assert {r["prompt_id"] for r in queued} == set(client.submitted)
    assert all(r.get("status") == "running" for r in queued)


def test_closing_with_the_switch_off_queues_nothing(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    _completed_image(db)
    client = _QueueSpyClient()
    win = OrigeneratorWindow(client, db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(win)

    win.close()

    assert client.submitted == []


def test_a_closing_branch_session_queues_nothing(qtbot, tmp_path, monkeypatch):
    # A preview's batch would outlive it in the shared ComfyUI as work the live
    # app can neither see nor cancel — every Generate after it waits behind jobs
    # "from another app" that were the user's own preview. Only the live install
    # schedules an absence.
    monkeypatch.setenv(ENV_FLAG, "1")
    db = Database(tmp_path / "t.db")
    _completed_image(db)
    client = _QueueSpyClient()
    state = AppState(tmp_path / "ui.json")
    state.set("experiments_enabled", True)  # seeded on from the live install
    win = OrigeneratorWindow(client, db, state)
    qtbot.addWidget(win)

    win.close()

    assert client.submitted == []
    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_opening_clears_the_experiments_the_last_absence_left_queued(qtbot, tmp_path):
    # Experiments belong to the closed app: whatever ComfyUI hadn't got through
    # is dropped as the window opens, so the GPU is the user's from the start.
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="exp-1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"positive_prompt": "x", "seed": 1}),
        workflow_json="{}", source="experiment",
    )
    db.update_generation("exp-1", status="running")
    client = _QueueSpyClient(running=["exp-1"])

    win = OrigeneratorWindow(client, db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(win)

    assert client.canceled == ["exp-1"]
    assert client.interrupts == 1  # it was mid-render — dequeuing alone wouldn't stop it
    assert db.get_generation("exp-1") is None
    assert win._gallery_view._reroll_jobs == {}  # and it is not adopted as a live job


def test_an_opening_branch_session_clears_nothing(qtbot, tmp_path, monkeypatch):
    # The other half of leaving experiments to the live install: a preview's
    # database is a copy of the live one, so the rows it would "clear" are the
    # live app's own experiments, running in the ComfyUI they share — dropping
    # them (and interrupting the one mid-render) destroys the absence's work.
    monkeypatch.setenv(ENV_FLAG, "1")
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="exp-1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"positive_prompt": "x", "seed": 1}),
        workflow_json="{}", source="experiment",
    )
    db.update_generation("exp-1", status="running")
    client = _QueueSpyClient(running=["exp-1"])

    win = OrigeneratorWindow(client, db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(win)

    assert client.canceled == []
    assert client.interrupts == 0
    assert db.get_generation("exp-1") is not None


def test_opening_with_unreviewed_experiments_presents_the_shelf(qtbot, tmp_path):
    # "What did it come up with while I was away?" — a launch with experiments
    # waiting opens on the review shelf instead of the last-visited folder.
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="exp-1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"positive_prompt": "x", "seed": 1}),
        workflow_json="{}", source="experiment",
    )
    db.update_generation(
        "exp-1", status="completed",
        output_files=json.dumps([{"filename": "exp.png", "subfolder": ""}]),
    )
    win = OrigeneratorWindow(ComfyUIClient(), db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(win)

    view = win._gallery_view
    view.refresh()
    assert view._tree.currentItem() is view._experiments_item
    assert view.visible_prompt_ids() == ["exp-1"]


def test_opening_without_pending_experiments_keeps_the_saved_folder(qtbot, tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("gallery_folder", "__recents__")
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="g-1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"positive_prompt": "x", "seed": 1}),
        workflow_json="{}",
    )
    db.update_generation(
        "g-1", status="completed",
        output_files=json.dumps([{"filename": "g.png", "subfolder": ""}]),
    )
    win = OrigeneratorWindow(ComfyUIClient(), db, state)
    qtbot.addWidget(win)

    view = win._gallery_view
    view.refresh()
    assert view._tree.currentItem() is view._recents_item


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


def test_reconnected_reroll_lights_its_tabs_generate_button(qtbot, tmp_path):
    # The reported gap: after a restart the bottom bar resumed but the Generate
    # button on the matching tab stayed idle. An i2v folder key depends on its start
    # frame's config, which the view can only resolve once its image rows are rebuilt
    # on show — so the button's generating state must be re-asserted then, not only at
    # reconnect time (when the image rows are still empty and the key can't match).
    db = Database(tmp_path / "t.db")
    # Rows a live tab must match carry the workflows' current versions, as runs
    # made by this app would — the settings key folds the version in.
    img_params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                      seed=1, positive_prompt="a face")
    db.insert_generation(prompt_id="img", workflow_name="sdxl_t2i",
                         workflow_version=WORKFLOW_REGISTRY["sdxl_t2i"].version,
                         positive_prompt="a face", seed=1,
                         params_json=json.dumps(img_params), workflow_json="{}")
    db.update_generation("img", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_t2i_img.png"}]))
    vid_params = dict(WORKFLOW_REGISTRY["wan22_i2v"].default_params(),
                      seed=7, positive_prompt="", input_image="sdxl_t2i_img.png [output]")
    db.insert_generation(prompt_id="rr", workflow_name="wan22_i2v",
                         workflow_version=WORKFLOW_REGISTRY["wan22_i2v"].version,
                         positive_prompt="", seed=7,
                         params_json=json.dumps(vid_params), workflow_json="{}")
    db.update_generation("rr", status="running")
    state = AppState(tmp_path / "ui.json")
    state.set("generate_tabs", {"tabs": [
        {"config": {"workflow_name": "wan22_i2v", "params": vid_params, "seed_is_random": True},
         "title": None},
    ], "current": 0})
    win = _window(qtbot, tmp_path, state)
    win._gallery_view.refresh()  # rebuilds the image rows, then re-asserts the button

    panel = win._gallery_view._info_tabs.current_config_panel()
    assert panel._generating is True


def test_reconnected_job_resumes_its_persisted_progress_on_the_bar(qtbot, tmp_path):
    # The user-visible payoff of persisting progress: after a restart the running-job
    # bar (fed by the in-flight items) resumes at the saved position, rather than an
    # indeterminate spin until ComfyUI's next per-step push.
    db = Database(tmp_path / "t.db")
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), seed=1, positive_prompt="a cat")
    db.insert_generation(prompt_id="rr", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="a cat", seed=1,
                         params_json=json.dumps(params), workflow_json="{}")
    db.update_generation("rr", status="running", progress_json=json.dumps(
        {"last_progress": [30, 50],
         "tracker": {"total": 50, "banked": 0, "stage_max": 50, "last_value": 30}}))

    win = _window(qtbot, tmp_path)

    item = next(it for it in win._gallery_view._inflight_items() if it.key == "rr")
    assert item.progress == (30, 50)


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
