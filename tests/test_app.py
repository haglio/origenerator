import builtins
import runpy
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import DEFAULT, MagicMock, patch

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


def test_warming_the_voice_runtimes_survives_any_install(monkeypatch):
    # The warm runs before Qt so ctranslate2/onnxruntime get a clean DLL init
    # (imported after Qt, the first model load is an access violation that
    # takes the app with it). The extra is optional and a broken install
    # raises OSError, not ImportError — neither may cost the boot.
    _warm_voice_runtimes()  # whatever this machine actually has

    real_import = builtins.__import__

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


# --- the boot sequence itself -------------------------------------------------
#
# What the tests above pin is what main *reaches*; these pin the order it
# reaches it in, which is the part a phase split can silently reorder. The order
# is load-bearing and stated in main's own comments: adoption before the import
# scan (so a preview's own rows are not rebuilt as lesser "imported" ones from
# the bare files), the enhancement fold after that scan, and the folder
# reconciles last because every backfill above can move a generation's folder.

# Each maintenance pass, as (module, attribute), in the order main runs them.
_MAINTENANCE_PASSES = (
    ("origenerator.branch_session", "adopt_branch_rows"),
    ("origenerator.branch_session", "adopt_branch_curation"),
    ("origenerator.reconcile", "reconcile_in_flight"),
    ("origenerator.importer", "import_comfyui_output"),
    ("origenerator.importer", "merge_video_sidecar_rows"),
    ("origenerator.importer", "backfill_unknown_workflows"),
    ("origenerator.importer", "backfill_model_and_lora_params"),
    ("origenerator.importer", "backfill_input_image"),
    ("origenerator.gallery", "fold_completed_enhancements"),
    ("origenerator.importer", "backfill_shared_thumbnails"),
    ("origenerator.log_backfill", "backfill_durations_from_logs"),
    ("origenerator.reconcile", "reconcile_folder_meta"),
    ("origenerator.reconcile", "reconcile_custom_folders"),
)


@contextmanager
def _a_faked_boot(record, *, passes=None, **patches):
    """``main`` with every collaborator faked, each maintenance pass recording.

    *record* collects the name of each pass as it runs, so a test can read the
    order back. *passes* overrides individual ones (``{"import_comfyui_output":
    a_mock}``) where a test needs one to misbehave; *patches* adds or replaces
    any other target by dotted path.
    """
    targets = {
        "origenerator.app._init_windows_taskbar_identity": DEFAULT,
        "origenerator.app._ensure_comfyui_server": DEFAULT,
        "origenerator.gui.loading_screen.LoadingScreen": DEFAULT,
        "origenerator.gui.main_window.OrigeneratorWindow": DEFAULT,
        "origenerator.gui.fun_time_bridge.FunTimeBridge": DEFAULT,
        "origenerator.app_state.AppState": DEFAULT,
        "origenerator.db.Database": DEFAULT,
        "origenerator.trash.Trash": DEFAULT,
        "origenerator.recovery.sweep": 0,
        "origenerator.comfyui_client.ComfyUIClient": DEFAULT,
        "PyQt6.QtWidgets.QApplication.exec": 0,
    }
    passes = passes or {}
    with ExitStack() as stack:
        for target, value in targets.items():
            stack.enter_context(
                patch(target) if value is DEFAULT else patch(target, return_value=value))
        for module, name in _MAINTENANCE_PASSES:
            stack.enter_context(patch(
                f"{module}.{name}",
                passes.get(name, MagicMock(
                    side_effect=lambda *a, _n=name, **k: record.append(_n) or 0))))
        for target, value in patches.items():
            stack.enter_context(patch(target, value))
        yield


def test_main_runs_every_maintenance_pass_in_the_documented_order(qapp):
    ran = []

    with _a_faked_boot(ran):
        with pytest.raises(SystemExit):
            main([])

    assert ran == [name for _, name in _MAINTENANCE_PASSES]


def test_a_failing_maintenance_pass_never_costs_the_launch(qapp):
    """Every pass is best-effort: a library the app cannot finish tidying is
    still a library it must open. Each is guarded on its own, so the one that
    throws costs only itself."""
    ran = []
    window = MagicMock()

    with _a_faked_boot(
        ran,
        passes={"import_comfyui_output": MagicMock(side_effect=OSError("no output dir"))},
        **{"origenerator.gui.main_window.OrigeneratorWindow": MagicMock(return_value=window)},
    ):
        with pytest.raises(SystemExit):
            main([])

    assert "import_comfyui_output" not in ran
    # ...and everything after it still ran, up to and including the window.
    assert ran[-1] == "reconcile_custom_folders"
    window.show.assert_called_once()


def test_a_branch_session_maintains_nothing_but_the_enhancement_fold(qapp):
    """A preview shows unlanded code, not a maintained library: its database is
    a seeded copy the live app already maintains. The fold is the exception —
    it rewrites rows the copy already holds, touching no file and reading no
    output history, so leaving it out would show enhancements standing as
    images of their own long after the live app stopped doing that."""
    ran = []

    with _a_faked_boot(ran), \
         patch("origenerator.branch_session.is_branch_session", return_value=True), \
         patch("origenerator.branch_session.seed_branch_db", return_value=True):
        with pytest.raises(SystemExit):
            main([])

    assert ran == ["fold_completed_enhancements"]


def test_a_branch_session_sweeps_no_deletions(qapp):
    """The seeded deletions point at the *live* install's held files, so both
    purging and restoring them from a preview would reach into the library the
    live app is still showing."""
    with _a_faked_boot([]) as _, \
         patch("origenerator.recovery.sweep", return_value=0) as sweep, \
         patch("origenerator.branch_session.is_branch_session", return_value=True), \
         patch("origenerator.branch_session.seed_branch_db", return_value=True):
        with pytest.raises(SystemExit):
            main([])

    sweep.assert_not_called()


def test_the_entry_point_hands_the_process_whatever_main_gives_back():
    """``python -m origenerator`` is how both .vbs launchers start the app, and
    the exit code is all either of them gets back out of the hidden console —
    so whatever ``main`` reports has to arrive there unchanged."""
    with patch("origenerator.app.main", return_value=7), \
         patch.object(sys, "argv", ["origenerator"]):
        with pytest.raises(SystemExit) as exit_:
            runpy.run_module("origenerator", run_name="__main__")

    assert exit_.value.code == 7


def test_a_real_boot_exits_with_the_code_the_qt_loop_returned(qapp):
    """End to end through the entry point: Qt's own exit code is the app's."""
    with _a_faked_boot([], **{"PyQt6.QtWidgets.QApplication.exec": MagicMock(return_value=3)}), \
         patch.object(sys, "argv", ["origenerator"]):
        with pytest.raises(SystemExit) as exit_:
            runpy.run_module("origenerator", run_name="__main__")

    assert exit_.value.code == 3
