import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# The persisted ComfyUI client id lives under this key in the UI state file.
_CLIENT_ID_KEY = "comfyui_client_id"


def resolve_comfyui_client_id(app_state) -> str:
    """The stable ComfyUI client id for this install: minted once, then persisted.

    ComfyUI routes a running prompt's progress, preview and completion messages
    only to the websocket client id that submitted it. Reusing the same id every
    launch is what lets a restart mid-generation reconnect to the job still running
    in ComfyUI and see its live progress again — without it, each launch's fresh id
    leaves the reconnected job's bar spinning forever because those messages are
    still being sent to the previous session's id.
    """
    stored = app_state.get(_CLIENT_ID_KEY)
    if isinstance(stored, str) and stored:
        return stored
    client_id = str(uuid.uuid4())
    app_state.set(_CLIENT_ID_KEY, client_id)
    app_state.save()
    return client_id


def _name_this_process() -> None:
    """Leave the launcher an interpreter that says "Origenerator" next time.

    Windows takes what it shows about a process from the file it was started
    from -- the Details tab's name, the Processes tab's description, the icon
    beside it -- so a plain ``python.exe`` puts Origenerator in the task list as
    one more anonymous "Python", indistinguishable from every other Python app
    on the machine.  That only matters until something strands a process, and
    then it is the whole difference between ending the right row and guessing.

    Naming this process on the way in is the one thing that cannot be done:
    writing the copy takes the very interpreter being named.  So each run makes
    it for the run after and ``launch_origenerator.vbs`` picks it up, which
    costs one launch, once.  The console interpreter, because that is the one
    the launcher runs -- it redirects the app's output into the launcher log.
    """
    try:
        from app_support.process_identity import ProcessNamer

        icon = Path(__file__).resolve().parent.parent / "icon.ico"
        ProcessNamer("Origenerator", icon=icon).prepare_launcher(
            "Origenerator", Path(sys.executable).with_name("python.exe"))
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


def _init_windows_taskbar_identity(identity: str | None = None) -> None:
    """Give Origenerator its own taskbar identity so the pinned launcher icon
    activates this window instead of spawning a second taskbar button.

    Sets the process AppUserModelID and stamps the matching ID onto the pinned
    shortcut, which is what lets Windows group them as one app. No-op off Windows.

    With *identity* (Fun Time hands its own), the process joins that identity
    instead so the hosted window groups with the session's taskbar button — and
    the pinned shortcut is left unstamped, since it belongs to the standalone
    launch and must keep activating that one.
    """
    if sys.platform != "win32":
        return
    from origenerator.win32 import (
        APP_USER_MODEL_ID,
        set_app_user_model_id,
        stamp_pinned_shortcuts,
    )
    try:
        set_app_user_model_id(identity or APP_USER_MODEL_ID)
    except OSError:
        pass  # Non-fatal — still try to stamp the shortcut below.
    if identity is None:
        stamp_pinned_shortcuts(APP_USER_MODEL_ID, include="origenerator")


def _bring_to_front(window) -> None:
    """Put a just-opened window in front, the way opening an app is supposed to.

    A launch here is slow — starting ComfyUI's server, scanning its whole output
    history, the backfills behind it — and nobody sits and watches that, so by
    the time there is a window to show, the last input event went to whatever
    the user moved on to. Windows hands the foreground to the process that got
    that input, and refuses it to this one; ``show()`` then puts Origenerator
    *behind* the window they are looking at, flashing the taskbar button as the
    only sign it opened at all.

    Qt's ``raise_``/``activateWindow`` ask down that same refused path, so they
    are the polite first try and the native call is what actually lands. Losing
    the race is cosmetic — the window is open either way — so no failure here may
    cost the launch.
    """
    window.raise_()
    window.activateWindow()
    if sys.platform != "win32":
        return
    try:
        from origenerator.win32 import force_foreground_window
        force_foreground_window(int(window.winId()))
    except Exception:
        pass  # cosmetic: a window behind is still a window


def _ensure_comfyui_server(logger, host, port, comfyui_dir, on_status=None, pump_events=None):
    import importlib.util
    import socket

    from origenerator.comfyui_client import comfyui_responding

    def port_open():
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            return False

    if comfyui_responding(host, port):
        logger.info("ComfyUI server already running on %s:%d", host, port)
        return

    if port_open():
        logger.warning(
            "Port %d is occupied by a non-ComfyUI server; ComfyUI cannot start there. "
            "Stop that process (or change COMFYUI_PORT) and relaunch Origenerator.",
            port,
        )
        return

    # Try to use ComfyUIApp's server launcher
    comfyuiapp_dir = comfyui_dir.parents[0]  # ComfyUIApp dir
    server_script = comfyuiapp_dir / "scripts" / "comfyui_server.py"
    if not server_script.exists():
        logger.warning("ComfyUI not running and launcher not found at %s", server_script)
        return

    try:
        spec = importlib.util.spec_from_file_location("comfyui_server", server_script)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        logger.info("Starting ComfyUI server via %s...", server_script)
        result = server.start(base_dir=comfyuiapp_dir, on_status=on_status, pump_events=pump_events)
        if result.started:
            logger.info("ComfyUI server started (PID %s)", result.pid)
        elif result.error:
            logger.warning("ComfyUI server failed to start: %s", result.error)
        else:
            logger.info("ComfyUI server was already running")
    except Exception as e:
        logger.warning("Failed to start ComfyUI server: %s", e)


def _warm_voice_runtimes() -> None:
    """Load the voice stack's native DLLs before Qt can spoil their welcome.

    Imported after PyQt6 is up, ctranslate2 — whisper's engine — dies with a
    plain access violation the moment the model loads, which took the whole
    app down the instant a spoken command triggered the first transcription;
    onnxruntime (whisper's VAD) fails its DLL init the same way. Both import
    clean the other way round — reproduced in both orders, offscreen, in this
    interpreter. Guarded per-module and per-failure: the voice extra is
    optional and a broken install surfaces as OSError rather than
    ImportError, and neither may cost the app its boot.
    """
    for module in ("onnxruntime", "ctranslate2"):
        try:
            __import__(module)
        except Exception:
            pass  # no voice extra (or a broken one): the app still boots


@dataclass(frozen=True)
class Library:
    """What the maintenance passes below work on.

    The live database and the ComfyUI client, plus the four folders they read
    and write. One record rather than four more parameters on every pass: they
    all draw from the same set, and a pass that needs none of it still has to be
    callable the same way as the one that needs all of it.
    """
    db: object
    client: object
    output_dir: Path
    thumb_dir: Path
    log_dir: Path
    worktrees: Path


@dataclass(frozen=True)
class BootPass:
    """One best-effort pass over the library, and everything the boot says about it.

    These were eleven copies of the same seven lines with two words changed --
    a status line, a call, a count logged when there was one, and a warning that
    swallowed whatever went wrong -- so adding a twelfth meant editing the boot
    rather than registering a pass. What varies between them is exactly this
    record: the splash line (``None`` to run under the previous pass's line, for
    a pass that is a second half rather than a step of its own), what to call,
    the message for a non-zero count, and the message for a failure.

    Every pass is best effort. A library the app cannot finish tidying is still
    a library it must open, so each is guarded on its own and a failure costs
    one warning line rather than the launch.
    """
    status: str | None
    run: Callable[[Library], object]
    failure: str
    counted: str | None = None


def _adopt_branch_rows(library: Library):
    """What a preview branch generated comes home as the rows that session
    recorded -- generated, full params -- before the import scan below can find
    the bare files and reconstruct lesser "imported" rows for them."""
    from origenerator.branch_session import adopt_branch_rows

    return adopt_branch_rows(
        library.db, library.worktrees, library.output_dir, library.thumb_dir)


def _adopt_branch_curation(library: Library):
    """And the bookmarks that session made on everything else. Separately
    guarded: a worktree database that defeats one pass has no bearing on the
    other, and neither is worth a failed launch."""
    from origenerator.branch_session import adopt_branch_curation

    return adopt_branch_curation(library.db, library.worktrees)


def _reconnect_to_running_generations(library: Library):
    """Resolve any generation left mid-run by a previous session against ComfyUI
    (finished-while-away, still-running, or gone). Runs before the import below
    so a finalized job's output is already recorded and isn't imported twice."""
    from origenerator.inflight import reconcile_in_flight

    reconcile_in_flight(library.db, library.client, library.output_dir, library.thumb_dir)


def _follow_moved_files(library: Library):
    """Repoint every recorded output file the user has since moved on disk.

    Before the scan below, which keys what it has already seen by path under the
    output dir: a file that moved reads there as one it has never seen, and it
    would rebuild a bare "imported" row beside the generated row that still
    holds the prompt and the settings."""
    from origenerator.relocate import relocate_moved_outputs

    return relocate_moved_outputs(library.db, library.output_dir)


def _import_new_files(library: Library):
    from origenerator.importer import import_comfyui_output

    return import_comfyui_output(library.output_dir, library.db, library.thumb_dir)


def _merge_video_sidecars(library: Library):
    """Fold each video's metadata-PNG sidecar into one playable gallery entry."""
    from origenerator.importer import merge_video_sidecar_rows

    return merge_video_sidecar_rows(library.db)


def _backfill_workflow_labels(library: Library):
    """Relabel any imports that predate filename-based workflow inference."""
    from origenerator.importer import backfill_unknown_workflows

    return backfill_unknown_workflows(library.db)


def _backfill_model_and_lora(library: Library):
    """Fill the base model and LoRA onto imports that predate reading them from
    the embedded graph, so they nest into the gallery's model/LoRA folders."""
    from origenerator.importer import backfill_model_and_lora_params

    return backfill_model_and_lora_params(library.db)


def _backfill_input_images(library: Library):
    """Fill input_image onto image-to-video imports that predate reading it from
    the embedded graph, so each video links back to the gallery image it was
    animated from (the same link a freshly generated i2v/flf2v already carries)."""
    from origenerator.importer import backfill_input_image

    return backfill_input_image(library.db)


def _fold_enhancements(library: Library):
    """A standalone enhance is an upgrade of an existing image, not its own
    generation: fold every finished one onto its source. After the scan, because
    an enhance the live app never recorded -- a branch session's above all --
    reaches here as a bare file, and the standalone image the scan just
    reconstructed from it is exactly what there is to fold away."""
    from origenerator.gallery import fold_completed_enhancements

    fold_completed_enhancements(library.db)


def _repair_thumbnails(library: Library):
    """Re-render any thumbnail an old filename-stem collision left wrong or
    missing, so each generation's thumbnail matches its own preview again."""
    from origenerator.importer import backfill_shared_thumbnails

    return backfill_shared_thumbnails(library.db, library.output_dir, library.thumb_dir)


def _recover_generation_times(library: Library):
    """Recover how long past generations took from ComfyUI's console logs, so
    estimates have history to draw on before any new run is timed live."""
    from origenerator.log_backfill import backfill_durations_from_logs

    return backfill_durations_from_logs(
        library.db, sorted(library.log_dir.glob("comfyui*.log")))


def _reconcile_bookmarks(library: Library):
    """Heal stars, custom names and hand-composed folders whose folder key
    drifted after a key formula change, and stamp identity onto live ones so the
    next change is handled automatically. Runs after the backfills above -- they
    can move a generation's folder by filling in its workflow/model/LoRA -- so
    the tree it reconciles against is final, and it is read once for both."""
    from origenerator.bookmark_reconcile import reconcile_bookmarks

    reconcile_bookmarks(library.db)


#: The library maintenance a live launch performs, in order. The order is
#: load-bearing: adoption before the import scan, the enhancement fold after it,
#: and the folder reconciles last because every backfill above can move a
#: generation's folder. tests/test_app.py reads this sequence back.
MAINTENANCE = (
    BootPass("Adopting branch-session results...", _adopt_branch_rows,
             counted="Adopted %d generations from branch sessions",
             failure="Branch-session adoption failed: %s"),
    BootPass(None, _adopt_branch_curation,
             counted="Adopted %d bookmark(s) from branch sessions",
             failure="Branch-session bookmark adoption failed: %s"),
    BootPass("Reconnecting to running generations...", _reconnect_to_running_generations,
             failure="Reconcile of in-flight generations failed: %s"),
    BootPass("Finding files that moved...", _follow_moved_files,
             counted="Followed %d output file(s) to where they moved",
             failure="Relocating moved output files failed: %s"),
    BootPass("Scanning for new images...", _import_new_files,
             counted="Imported %d existing files from ComfyUI output",
             failure="Import failed: %s"),
    BootPass("Tidying up video previews...", _merge_video_sidecars,
             counted="Consolidated %d video sidecar previews",
             failure="Sidecar consolidation failed: %s"),
    BootPass("Updating workflow labels...", _backfill_workflow_labels,
             counted="Relabelled %d previously-unknown imports",
             failure="Workflow backfill failed: %s"),
    BootPass("Sorting by model and LoRA...", _backfill_model_and_lora,
             counted="Backfilled model/LoRA for %d imports",
             failure="Model/LoRA backfill failed: %s"),
    BootPass("Linking videos to their source images...", _backfill_input_images,
             counted="Backfilled source image for %d video imports",
             failure="Input-image backfill failed: %s"),
    BootPass("Folding enhancements into their images...", _fold_enhancements,
             failure="Enhancement fold failed: %s"),
    BootPass("Repairing thumbnails...", _repair_thumbnails,
             counted="Repaired %d colliding thumbnails",
             failure="Thumbnail repair failed: %s"),
    BootPass("Recovering generation times...", _recover_generation_times,
             counted="Backfilled generation time for %d imports from logs",
             failure="Duration backfill failed: %s"),
    BootPass("Restoring folder bookmarks...", _reconcile_bookmarks,
             failure="Folder bookmark reconcile failed: %s"),
)

#: What a branch session maintains instead: the two passes that are not
#: maintenance of the library at all. Every pass above already ran on the
#: database it was seeded from, and re-running them would only slow the preview
#: down (the import scan alone reads the whole output history) and write records
#: the live install then imports as duplicates of its own. These two write no
#: record and touch no file -- each only rewrites rows the seeded copy already
#: holds -- and left out, each shows a difference in the copy rather than in the
#: code: enhancements standing as images of their own long after the live app
#: stopped doing that, and a generation drawing its thumbnail and nothing else
#: because its file moved. The moved-file pass reads the output *tree* (one
#: listing, not the history behind it), which is what keeps it affordable here.
BRANCH_SESSION_MAINTENANCE = (
    BootPass("Finding files that moved...", _follow_moved_files,
             counted="Followed %d output file(s) to where they moved",
             failure="Relocating moved output files failed: %s"),
    BootPass("Folding enhancements into their images...", _fold_enhancements,
             failure="Enhancement fold failed: %s"),
)


def _run_maintenance(library: Library, passes, status, logger) -> None:
    """Run each pass, saying what it is doing and surviving what it cannot do."""
    for boot_pass in passes:
        if boot_pass.status is not None:
            status(boot_pass.status)
        try:
            count = boot_pass.run(library)
            if boot_pass.counted and count:
                logger.info(boot_pass.counted, count)
        except Exception as e:
            logger.warning(boot_pass.failure, e)


def _configure_logging(state_dir: Path):
    """The app's log: the console the launcher redirects, and a rotating file."""
    import logging
    from logging.handlers import RotatingFileHandler

    log_handlers = [logging.StreamHandler()]
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        log_handlers.append(RotatingFileHandler(
            state_dir / "origenerator.log", maxBytes=1_000_000, backupCount=2,
            encoding="utf-8",
        ))
    except OSError:
        pass  # console logging still works if the file can't be opened
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=log_handlers,
    )
    return logging.getLogger(__name__)


def _open_the_splash(fun_time, app):
    """The boot's own window, or ``None`` when the session owns that job.

    Shown before the slow imports and boot work so the user gets immediate
    feedback; each phase updates its status line, and ``processEvents`` keeps the
    busy sweep animating while the main thread is blocked.

    Hosted by Fun Time there is NO splash at all: the session's own loading
    screen owns the boot experience and this app boots parked, so a splash here
    has no audience -- and it is an always-on-top window whose lifetime is the
    boot, which on a slow boot left it sitting over a satellite region after the
    session revealed ("the landscape player is behind other windows on startup":
    the covering window was this splash). The boot phases still land in the log.
    """
    if fun_time is not None:
        return None
    from origenerator.gui.loading_screen import LoadingScreen

    loading = LoadingScreen()
    loading.show()
    _bring_to_front(loading)
    app.processEvents()
    return loading


def _status_line(loading, app, logger):
    """Where a phase says what it is doing: the splash, or the log without one."""
    def status(message: str) -> None:
        if loading is not None:
            loading.set_status(message)
        else:
            logger.info("Boot: %s", message)
        app.processEvents()

    return status


def _open_database(db_path: Path, *, branch_session: bool, logger):
    """The live database -- seeded from the primary install first in a preview.

    A branch session (a worktree run via launch_preview_branch.vbs) is here to
    show unlanded code, not to maintain the library, so it starts from the
    primary install's database rather than re-scanning ComfyUI's whole history
    into a fresh one (see origenerator.branch_session).
    """
    if branch_session:
        from origenerator.branch_session import seed_branch_db
        from origenerator.config import project_dir
        try:
            primary_db = project_dir("origenerator") / "state" / db_path.name
            if seed_branch_db(primary_db, db_path):
                logger.info("Branch session: database seeded from %s", primary_db)
        except Exception as e:
            logger.warning("Branch DB seed failed (starting empty): %s", e)
    from origenerator.db import Database

    return Database(db_path)


def _sweep_the_recovery_bin(db, state_dir: Path, logger) -> None:
    """Age out the recovery bin: deletions past their window are ended for good
    and any trash folder no surviving record names is reclaimed (see
    origenerator.recovery).

    Never in a branch session -- its database is a copy, so the deletions it
    inherited point at the *live* install's held files, and both purging and
    restoring them from there would reach into the library the live app is
    still showing.
    """
    from origenerator import recovery
    from origenerator.branch_session import session_trash
    try:
        expired = recovery.sweep(db, session_trash(state_dir / "trash"))
        if expired:
            logger.info("Recovery bin: ended %d expired deletion(s)", expired)
    except Exception as e:
        logger.warning("Recovery-bin sweep failed: %s", e)


def _build_window(client, db, app_state, fun_time):
    """The main window, shown -- or parked, when a session hosts it."""
    from origenerator.gui.main_window import OrigeneratorWindow

    window = OrigeneratorWindow(client, db, app_state, fun_time=fun_time)
    if fun_time is not None:
        # The session's channels: its verbs onto the region shows, the paused
        # flag over them, and the occupancy status back.  Parented to the
        # window so it lives exactly as long as the app.
        from origenerator.gui.fun_time_bridge import FunTimeBridge
        FunTimeBridge(fun_time, window._gallery_view, parent=window)
        # Parked until the session's own mode switch restores it: the session
        # may be in player mode, where popping over the RFB would be wrong.
        window.showMinimized()
    else:
        window.show()
    return window


def _refuse_an_incomplete_overlay(missing: tuple[str, ...], fun_time) -> int:
    """Say which keys `content.local.json` is short of, and stop the launch.

    That file is git-ignored and hand-maintained, so it does not gain a key when
    the app does -- and the committed example it is written from has gone from
    three keys to nine in six weeks. Three of those nine are read with a bare
    subscript, so an overlay one release behind used to be a dead icon: no
    window, and the traceback in a launcher log nobody opens. The other six went
    quietly one feature at a time, which is worse in its own way -- a stroke
    aimed at the wrong part of the frame reads as the model having a bad day.

    One rule for all nine, then: name what is missing and do not start. A key
    can be left EMPTY to switch that feature off, so this is not a demand to
    configure what you do not use.

    Nothing has been logged yet at this point -- logging is configured from
    ``config``, which is what a missing key stops from importing -- so this goes
    to the console the launcher redirects into ``state/origenerator_launcher.log``,
    and to a dialog when there is a screen to put one on. Hosted by Fun Time
    there is not: nobody is at this window to dismiss a modal and it would sit
    over one of the session's players, which is why the splash is suppressed
    there too.
    """
    from origenerator.content import EXAMPLE_CONTENT, LOCAL_CONTENT

    message = (
        f"{LOCAL_CONTENT} is missing {len(missing)} key(s) this version needs:\n\n"
        + "\n".join(f"    {key}" for key in missing)
        + f"\n\nCopy them from {EXAMPLE_CONTENT.name}. A key can be left empty "
          "to switch that feature off."
    )
    print(f"Origenerator: {message}", file=sys.stderr)
    if fun_time is None:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Origenerator: incomplete content overlay", message)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Boot the app and run it; return the code the process should exit with.

    ``sys.exit`` is ``__main__.py``'s, not this function's: both .vbs launchers
    run ``python -m origenerator`` and read the code back out of a hidden
    console, so the value has to reach the process either way -- but a ``main``
    that returns it can be called and read by a test, where one that raises
    can only be caught.
    """
    from origenerator.fun_time_mode import parse_app_args

    app_args = parse_app_args(sys.argv[1:] if argv is None else argv)
    fun_time = app_args.fun_time
    if fun_time is not None:
        # Hosted, draw at the session's HUD scale (origenerator.ui_scale says
        # why). Here and not later: Qt reads QT_SCALE_FACTOR as the platform
        # plugin starts, so it has to be set before PyQt6 is imported at all.
        from origenerator.ui_scale import apply_hosted_scale
        apply_hosted_scale()
    _warm_voice_runtimes()  # must precede the first PyQt6 import below
    _init_windows_taskbar_identity(app_args.taskbar_identity)
    _name_this_process()

    from PyQt6.QtWidgets import QApplication

    # Qt gets no argv of ours: the launch contract (see fun_time_mode) is parsed
    # above, and letting Qt re-read those flags would only invite collisions.
    app = QApplication.instance() or QApplication(sys.argv[:1])

    # Before config, because config is the first thing a missing key stops from
    # importing, and before the splash, because there is nothing to put one over.
    from origenerator.content import missing_overlay_keys
    missing = missing_overlay_keys()
    if missing:
        return _refuse_an_incomplete_overlay(missing, fun_time)

    from origenerator.config import (
        COMFYUI_DIR,
        COMFYUI_HOST,
        COMFYUI_LOG_DIR,
        COMFYUI_OUTPUT_DIR,
        COMFYUI_PORT,
        DB_PATH,
        PROJECT_DIR,
        STATE_DIR,
        THUMB_DIR,
        UI_STATE_PATH,
    )

    logger = _configure_logging(STATE_DIR)

    # The one place the stylesheet is applied, and it must be the application:
    # QToolTip popups are top-level widgets a window-level sheet never reaches,
    # so styling per-window left every tooltip on the native Windows 11 dark
    # palette — which renders them unreadable, i.e. effectively missing.
    from origenerator.gui.stylesheet import build_stylesheet
    app.setStyleSheet(build_stylesheet())

    if app_args.check_launch:
        # Everything the launch imports, imported -- including the modules that
        # are only reached further down, which are where a break hides.  Nothing
        # is opened or shown: this returns before the database, ComfyUI and the
        # first window, so a hosting session's test can run the real command
        # against a live machine without touching either.
        from origenerator.app_state import AppState
        from origenerator.branch_session import is_branch_session
        from origenerator.comfyui_client import ComfyUIClient
        from origenerator.db import Database  # noqa: F401
        from origenerator.gui.main_window import OrigeneratorWindow  # noqa: F401
        logger.info("Launch check passed (%s)", sys.executable)
        return 0

    loading = _open_the_splash(fun_time, app)
    status = _status_line(loading, app, logger)

    status("Starting ComfyUI server...")
    _ensure_comfyui_server(
        logger, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_DIR,
        on_status=status, pump_events=app.processEvents,
    )

    from origenerator.branch_session import is_branch_session
    branch_session = is_branch_session()

    status("Opening the image library...")
    db = _open_database(DB_PATH, branch_session=branch_session, logger=logger)
    if not branch_session:
        _sweep_the_recovery_bin(db, STATE_DIR, logger)

    # One AppState for the whole app: it holds the persisted ComfyUI client id the
    # client reconnects under, and is handed to the window for the rest of the
    # session state (open tabs, gallery folder, geometry).
    from origenerator.app_state import AppState
    app_state = AppState(UI_STATE_PATH)

    from origenerator.comfyui_client import ComfyUIClient
    client = ComfyUIClient(
        host=COMFYUI_HOST, port=COMFYUI_PORT,
        client_id=resolve_comfyui_client_id(app_state),
    )

    if branch_session:
        status("Skipping library maintenance (branch session)...")
        logger.info("Branch session: library maintenance left to the live app")
    _run_maintenance(
        Library(db=db, client=client, output_dir=COMFYUI_OUTPUT_DIR,
                thumb_dir=THUMB_DIR, log_dir=COMFYUI_LOG_DIR,
                worktrees=PROJECT_DIR / ".claude" / "worktrees"),
        BRANCH_SESSION_MAINTENANCE if branch_session else MAINTENANCE,
        status, logger,
    )

    status("Connecting to ComfyUI...")
    client.start()

    status("Building the interface...")
    window = _build_window(client, db, app_state, fun_time)

    if loading is not None:
        loading.close()
        # Let the splash's closing settle before asking for the foreground:
        # Windows hands activation on from a closing window to whatever is next
        # in the Z-order, and unpumped that lands *after* the request below and
        # undoes it.
        app.processEvents()
    if fun_time is None:
        # Hosted, the session decides what is in front — this window is parked
        # until the satellites switch to origenerator mode, and asking for the
        # foreground here would pull it over the room mid-boot.
        _bring_to_front(window)

    exit_code = app.exec()
    client.stop()
    client.wait(3000)
    return exit_code
