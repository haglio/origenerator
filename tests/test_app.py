import builtins
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from origenerator.app import (
    _bring_to_front,
    _ensure_comfyui_server,
    _init_windows_taskbar_identity,
    _warm_voice_runtimes,
    main,
    resolve_comfyui_client_id,
)
from origenerator.app_state import AppState
from origenerator.comfyui_client import ComfyUIClient

COMFYUI_DIR = Path("C:/x/ComfyUIApp/ComfyUI")


def test_warming_the_voice_runtimes_reaches_for_both_and_survives_any_install(monkeypatch):
    # The warm runs before Qt so ctranslate2/onnxruntime get a clean DLL init
    # (imported after Qt, the first model load is an access violation that
    # takes the app with it). So it has to actually reach for them — emptied to a
    # bare return it ran green. The extra is optional and a broken install
    # raises OSError, not ImportError — neither may cost the boot.
    real_import = builtins.__import__
    asked = []

    def recording(name, *args, **kwargs):
        asked.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", recording)
    _warm_voice_runtimes()  # whatever this machine actually has

    assert {"ctranslate2", "onnxruntime"} <= set(asked)

    def broken(name, *args, **kwargs):
        if name in ("onnxruntime", "ctranslate2"):
            raise OSError("DLL initialization routine failed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    _warm_voice_runtimes()  # and a machine where both are broken


def test_resolve_client_id_mints_and_persists_when_absent(tmp_path):
    # First launch: no id yet, so one is minted and written to the state file, so the
    # next launch reads it back rather than minting a different one.
    path = tmp_path / "ui.json"
    client_id = resolve_comfyui_client_id(AppState(path))

    assert client_id
    assert AppState(path).get("comfyui_client_id") == client_id


def test_resolve_client_id_reuses_the_persisted_value(tmp_path):
    state = AppState(tmp_path / "ui.json")
    state.set("comfyui_client_id", "existing-id")

    assert resolve_comfyui_client_id(state) == "existing-id"


def test_resolve_client_id_replaces_a_non_string_value(tmp_path):
    # A corrupt/hand-edited state value must not become a bad clientId; mint instead.
    state = AppState(tmp_path / "ui.json")
    state.set("comfyui_client_id", 12345)

    client_id = resolve_comfyui_client_id(state)

    assert isinstance(client_id, str) and client_id


def test_client_id_is_stable_across_launches(tmp_path, qtbot):
    # The crux of restart recovery: two launches (two AppStates over the same file)
    # give ComfyUIClients the same id, so ComfyUI keeps routing a running job's live
    # progress/preview/completion messages to the reconnecting session.
    path = tmp_path / "ui.json"
    first = ComfyUIClient(client_id=resolve_comfyui_client_id(AppState(path)))
    second = ComfyUIClient(client_id=resolve_comfyui_client_id(AppState(path)))

    assert first.client_id == second.client_id


def test_init_windows_taskbar_identity_sets_aumid_and_stamps():
    with patch("origenerator.app.sys.platform", "win32"), \
         patch("origenerator.win32.set_app_user_model_id") as mock_set_id, \
         patch("origenerator.win32.stamp_pinned_shortcuts") as mock_stamp:
        _init_windows_taskbar_identity()

    mock_set_id.assert_called_once_with("FunTime.Origenerator")
    mock_stamp.assert_called_once_with("FunTime.Origenerator", include="origenerator")


def test_init_windows_taskbar_identity_noop_off_windows():
    with patch("origenerator.app.sys.platform", "linux"), \
         patch("origenerator.win32.set_app_user_model_id") as mock_set_id, \
         patch("origenerator.win32.stamp_pinned_shortcuts") as mock_stamp:
        _init_windows_taskbar_identity()

    mock_set_id.assert_not_called()
    mock_stamp.assert_not_called()


class TestBringToFront:
    """Opening the app has to put it in front of what the user is looking at.
    The boot is slow enough that they click elsewhere while it runs, and Windows
    then refuses this process the foreground — silently — so ``show()`` alone
    leaves the window behind their other windows."""

    def test_raises_activates_and_takes_the_foreground(self):
        window = MagicMock()
        window.winId.return_value = 4242

        with patch("origenerator.app.sys.platform", "win32"), \
             patch("origenerator.win32.force_foreground_window") as force:
            _bring_to_front(window)

        window.raise_.assert_called_once_with()
        window.activateWindow.assert_called_once_with()
        # Qt's own activation asks down the path Windows refuses, so the native
        # call is the one that actually lands.
        force.assert_called_once_with(4242)

    def test_noop_off_windows(self):
        window = MagicMock()

        with patch("origenerator.app.sys.platform", "linux"), \
             patch("origenerator.win32.force_foreground_window") as force:
            _bring_to_front(window)

        force.assert_not_called()
        window.raise_.assert_called_once_with()

    def test_a_refused_foreground_never_costs_the_launch(self):
        # Being behind is cosmetic; failing to open is not.
        window = MagicMock()
        window.winId.return_value = 4242

        with patch("origenerator.app.sys.platform", "win32"), \
             patch("origenerator.win32.force_foreground_window",
                   side_effect=OSError("denied")):
            _bring_to_front(window)


def test_ensure_server_warns_when_port_held_by_non_comfyui():
    logger = MagicMock()
    with patch("origenerator.comfyui_client.comfyui_responding", return_value=False), \
         patch("socket.create_connection"), \
         patch("importlib.util.spec_from_file_location") as mock_spec:
        _ensure_comfyui_server(logger, "127.0.0.1", 8188, COMFYUI_DIR)

    mock_spec.assert_not_called()
    assert logger.warning.called
    msg = logger.warning.call_args[0][0].lower()
    assert "occupied" in msg or "not comfyui" in msg


def test_ensure_server_noop_when_comfyui_already_responding():
    logger = MagicMock()
    with patch("origenerator.comfyui_client.comfyui_responding", return_value=True), \
         patch("importlib.util.spec_from_file_location") as mock_spec:
        _ensure_comfyui_server(logger, "127.0.0.1", 8188, COMFYUI_DIR)

    mock_spec.assert_not_called()
    logger.warning.assert_not_called()


def test_ensure_server_forwards_status_and_pump_callbacks_to_launcher():
    logger = MagicMock()
    on_status = MagicMock()
    pump_events = MagicMock()
    fake_server = MagicMock()
    fake_server.start.return_value = MagicMock(started=True, pid=4321, error=None)

    with patch("origenerator.comfyui_client.comfyui_responding", return_value=False), \
         patch("socket.create_connection", side_effect=OSError), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("importlib.util.spec_from_file_location"), \
         patch("importlib.util.module_from_spec", return_value=fake_server):
        _ensure_comfyui_server(
            logger, "127.0.0.1", 8188, COMFYUI_DIR,
            on_status=on_status, pump_events=pump_events,
        )

    fake_server.start.assert_called_once()
    kwargs = fake_server.start.call_args.kwargs
    assert kwargs["on_status"] is on_status
    assert kwargs["pump_events"] is pump_events


def test_main_shows_loading_screen_during_boot_and_closes_it_after_window(qapp):
    events = []

    loading = MagicMock()
    loading.show.side_effect = lambda: events.append("loading.show")
    loading.close.side_effect = lambda: events.append("loading.close")

    window = MagicMock()
    window.show.side_effect = lambda: events.append("window.show")

    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen", return_value=loading), \
         patch("origenerator.gui.main_window.OrigeneratorWindow", return_value=window), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash"), \
         patch("origenerator.importer.import_comfyui_output", return_value=0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main([])

    # Splash is visible for the whole boot and dismissed once the window shows.
    assert events == ["loading.show", "window.show", "loading.close"]
    # The boot phases drive the splash status text.
    statuses = " ".join(str(c.args[0]) for c in loading.set_status.call_args_list)
    assert "ComfyUI server" in statuses


def test_main_fronts_the_window_after_the_splash_is_gone(qapp):
    """The window is brought forward LAST — after the splash closes. Windows
    hands a closing window's activation on to whatever is next in the Z-order,
    so fronting before that would be undone by the splash's own departure."""
    events = []

    loading = MagicMock()
    loading.close.side_effect = lambda: events.append("loading.close")

    window = MagicMock()
    window.show.side_effect = lambda: events.append("window.show")

    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen", return_value=loading), \
         patch("origenerator.gui.main_window.OrigeneratorWindow", return_value=window), \
         patch("origenerator.app._bring_to_front",
               side_effect=lambda w: events.append(
                   "front:window" if w is window else "front:loading")), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash"), \
         patch("origenerator.importer.import_comfyui_output", return_value=0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main([])

    assert events == [
        "front:loading",  # the splash leads the launch too, not just the window
        "window.show",
        "loading.close",
        "front:window",
    ]


def test_main_reconciles_in_flight_before_importing(qapp):
    """In-flight generations are resolved against ComfyUI before the disk import,
    so a job finalized from history isn't then re-imported as a duplicate."""
    calls = []
    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen"), \
         patch("origenerator.gui.main_window.OrigeneratorWindow"), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash"), \
         patch("origenerator.reconcile.reconcile_in_flight",
               side_effect=lambda *a, **k: calls.append("reconcile")), \
         patch("origenerator.importer.import_comfyui_output",
               side_effect=lambda *a, **k: calls.append("import") or 0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main([])

    assert calls[:2] == ["reconcile", "import"]


def test_main_ages_out_the_recovery_bin_on_startup(qapp):
    """Deletions past their window are ended, and the trash they no longer hold
    is reclaimed, before the window opens."""
    trash = MagicMock()
    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen"), \
         patch("origenerator.gui.main_window.OrigeneratorWindow"), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash", return_value=trash), \
         patch("origenerator.recovery.sweep", return_value=0) as sweep, \
         patch("origenerator.importer.import_comfyui_output", return_value=0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main([])

    sweep.assert_called_once()
    assert sweep.call_args.args[1] is trash


def test_main_connects_the_client_under_the_persisted_id(qapp):
    # The client must connect under the id persisted across launches, so a restart
    # reconnects to the job ComfyUI is still running (it targets that job's live
    # messages at this id). Without it, each launch's fresh id leaves the
    # reconnected job's progress bar spinning forever.
    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen"), \
         patch("origenerator.gui.main_window.OrigeneratorWindow"), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.app.resolve_comfyui_client_id", return_value="persisted-id"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash"), \
         patch("origenerator.importer.import_comfyui_output", return_value=0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient") as mock_client, \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main([])

    assert mock_client.call_args.kwargs["client_id"] == "persisted-id"


def test_taskbar_identity_override_skips_the_pinned_shortcut_stamp():
    # Fun Time hands its own AUMID so the hosted window groups with the session;
    # the pinned Origenerator shortcut keeps the standalone identity, so it is
    # left unstamped.
    with patch("origenerator.app.sys.platform", "win32"), \
         patch("origenerator.win32.set_app_user_model_id") as mock_set_id, \
         patch("origenerator.win32.stamp_pinned_shortcuts") as mock_stamp:
        _init_windows_taskbar_identity("FunTime.App")

    mock_set_id.assert_called_once_with("FunTime.App")
    mock_stamp.assert_not_called()


def test_main_in_fun_time_mode_parks_the_window_and_threads_the_session(qapp):
    window = MagicMock()
    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen"), \
         patch("origenerator.gui.main_window.OrigeneratorWindow",
               return_value=window) as mock_window, \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash"), \
         patch("origenerator.importer.import_comfyui_output", return_value=0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("origenerator.gui.fun_time_bridge.FunTimeBridge") as mock_bridge, \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main(["--fun-time", "--x", "5", "--y", "6",
                  "--width", "700", "--height", "900"])

    session = mock_window.call_args.kwargs["fun_time"]
    assert (session.main_rect.x, session.main_rect.y) == (5, 6)
    # The session's channels are wired up on the gallery.
    assert mock_bridge.call_args.args[0] is session
    # Parked until the session's own mode switch restores it: the session may be
    # in player mode, where popping over the Random Favs Browser is wrong.
    window.showMinimized.assert_called_once()
    window.show.assert_not_called()


def test_main_in_fun_time_mode_shows_no_splash(qapp):
    """Hosted, the app boots with no splash at all: the session's own loading
    screen owns the boot's feedback, and an always-on-top splash of ours can
    outlive the session's reveal and sit over one of its players — reported
    as 'the landscape player is behind other windows on startup', and the
    covering window a z-order walk named was exactly this splash."""
    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen") as mock_loading, \
         patch("origenerator.gui.main_window.OrigeneratorWindow"), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.app_state.AppState"), \
         patch("origenerator.db.Database"), \
         patch("origenerator.trash.Trash"), \
         patch("origenerator.importer.import_comfyui_output", return_value=0), \
         patch("origenerator.importer.merge_video_sidecar_rows", return_value=0), \
         patch("origenerator.importer.backfill_unknown_workflows", return_value=0), \
         patch("origenerator.importer.backfill_shared_thumbnails", return_value=0), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("origenerator.gui.fun_time_bridge.FunTimeBridge"), \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main(["--fun-time", "--x", "5", "--y", "6",
                  "--width", "700", "--height", "900"])

    mock_loading.assert_not_called()


# --- the launch over a library of our own -------------------------------------
#
# The tests above hand main a MagicMock database, whose every query answers with
# an empty iterable — so the boot phases their patch chain does not name run over
# nothing at all and are asserted by nothing. Four separate mutations to main
# survived them: the folder-bookmark reconcile deleted, the duration backfill's
# result thrown away, a branch preview sweeping the LIVE install's recovery bin,
# and the branch database never seeded. These boot the same main over a real
# database under tmp_path and read each phase's effect off it afterwards.

@pytest.fixture
def library(tmp_path, monkeypatch):
    """Point every path the launch reads at tmp_path, and hand back its database.

    Also what keeps these tests out of the checkout's own state/ directory, which
    is where the launch writes its log, its trash and its database by default.
    """
    from origenerator import config

    state = tmp_path / "state"
    for name, path in (("STATE_DIR", state),
                       ("COMFYUI_OUTPUT_DIR", tmp_path / "output"),
                       ("COMFYUI_LOG_DIR", tmp_path / "logs"),
                       ("THUMB_DIR", tmp_path / "thumbs"),
                       ("PROJECT_DIR", tmp_path / "checkout")):
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(config, "DB_PATH", state / "origenerator.db")
    monkeypatch.setattr(config, "UI_STATE_PATH", state / "ui.json")
    return config.DB_PATH


def _boot(library_path, argv=()):
    """Run the launch, patching only the boundary: the splash, the window, and
    ComfyUI. Every maintenance pass runs for real."""
    from origenerator.db import Database

    with patch("origenerator.app._init_windows_taskbar_identity"), \
         patch("origenerator.gui.loading_screen.LoadingScreen"), \
         patch("origenerator.gui.main_window.OrigeneratorWindow"), \
         patch("origenerator.app._ensure_comfyui_server"), \
         patch("origenerator.comfyui_client.ComfyUIClient"), \
         patch("PyQt6.QtWidgets.QApplication.exec", return_value=0):
        with pytest.raises(SystemExit):
            main(list(argv))
    return Database(library_path)


def _completed_image(db, prompt_id, **params):
    """One finished SDXL image in the library, fabricated whole."""
    import json

    values = {"positive_prompt": "a paper boat", "steps": 30, "seed": 1, **params}
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="v002", params_json=json.dumps(values),
                         workflow_json="{}")
    db.update_generation(
        prompt_id, status="completed",
        output_files=json.dumps([{"filename": f"sdxl_t2i_{prompt_id}.png",
                                  "subfolder": "image"}]),
    )
    return db.get_generation(prompt_id)


def test_the_launch_dresses_the_application_in_the_stylesheet(qapp, library):
    # QToolTip popups are top-level widgets: a window-level sheet never reaches
    # them, which is exactly how every tooltip in the app went missing once. It
    # has to be the QApplication, and it has to be here — asserted by reading the
    # sheet back off the application, because the same call sitting in a comment
    # reads identically to anything that only greps app.py for the line.
    from origenerator.gui.stylesheet import build_stylesheet

    prior = qapp.styleSheet()
    qapp.setStyleSheet("")  # so a sheet an earlier launch left on cannot answer for this one
    try:
        _boot(library)

        assert qapp.styleSheet() == build_stylesheet()
    finally:
        qapp.setStyleSheet(prior)  # every later test renders in the chrome it expected


def test_the_launch_heals_a_bookmark_whose_folder_key_drifted(qapp, library):
    # The reconcile is why a star survives a change to the key formula. Deleting
    # both its calls left the boot tests green, and the star would simply be gone
    # from the folder the user put it on.
    from origenerator import gallery
    from origenerator.db import Database

    row = _completed_image(Database(library), "p1")
    legacy = gallery.legacy_settings_folder_key(row)
    Database(library).set_folder_starred(legacy, True)

    db = _boot(library)

    meta = db.folder_meta_map()
    assert meta.get(gallery.settings_folder_key(row), {}).get("starred") is True
    assert legacy not in meta  # and the stale key is not left behind beside it


def test_the_launch_recovers_generation_times_from_comfyuis_logs(qapp, library):
    # Estimates have no history to draw on until this runs, and throwing its
    # result away left the boot tests green.
    from datetime import datetime, timezone

    from origenerator import config
    from origenerator.db import Database

    db = Database(library)
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="imported", params_json="{}",
                         workflow_json="{}", source="imported")
    finished = datetime(2026, 6, 29, 12, 20, 53).timestamp()
    db.update_generation(
        "p1", status="completed",
        completed_at=datetime.fromtimestamp(finished, tz=timezone.utc).isoformat())
    (config.COMFYUI_LOG_DIR / "comfyui.log").write_text(
        "[2026-06-29 12:20:53.244] Prompt executed in 15.26 seconds\n",
        encoding="utf-8")

    db = _boot(library)

    assert db.get_generation("p1")["duration_seconds"] == 15.26


def _held_deletion(library_path, prompt_id, *, days_ago):
    """A deletion held ``days_ago`` days — old enough to be swept, or not."""
    import sqlite3
    from contextlib import closing
    from datetime import datetime, timedelta, timezone

    from origenerator.db import Database

    db = Database(library_path)
    row = _completed_image(db, prompt_id)
    db.delete_generation(prompt_id)
    db.record_deletion(prompt_id, row, {"moves": [], "subdir": None})
    then = (datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with closing(sqlite3.connect(library_path)) as conn:
        conn.execute("UPDATE deletions SET deleted_at = ?", (then,))
        conn.commit()


def test_the_launch_ends_a_deletion_that_has_outlived_its_window(qapp, library):
    _held_deletion(library, "p1", days_ago=61)

    db = _boot(library)

    assert db.list_deletions() == []  # the "60 days, then it's really gone" half


def test_a_branch_preview_sweeps_nothing_out_of_the_recovery_bin(
        qapp, library, monkeypatch):
    # A preview's database is a copy, so every deletion it inherits points at the
    # LIVE install's held files: purging one from here takes the only copy of
    # something the running app is still showing. Letting the sweep run anyway
    # left the boot tests green.
    from origenerator.branch_session import ENV_FLAG

    _held_deletion(library, "p1", days_ago=61)
    monkeypatch.setenv(ENV_FLAG, "1")

    db = _boot(library)

    assert [record["prompt_id"] for record in db.list_deletions()] == ["p1"]


def test_a_branch_preview_starts_from_the_live_installs_library(
        qapp, library, monkeypatch, tmp_path):
    # Without the seed the preview comes up on an empty database with no library
    # at all, and there is nothing in it to judge the branch by. Skipping the seed
    # left the boot tests green.
    from origenerator import config
    from origenerator.branch_session import ENV_FLAG
    from origenerator.db import Database

    primary = tmp_path / "primary"
    _completed_image(Database(primary / "state" / library.name), "live-1")
    monkeypatch.setattr(config, "project_dir", lambda name, *a, **kw: primary)
    monkeypatch.setenv(ENV_FLAG, "1")
    assert not library.exists()  # the preview has no database of its own yet

    db = _boot(library)

    assert [row["prompt_id"] for row in db.list_generations()] == ["live-1"]
