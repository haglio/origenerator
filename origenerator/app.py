import sys
import uuid

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
        from pathlib import Path as _Path

        icon = _Path(__file__).resolve().parent.parent / "icon.ico"
        ProcessNamer("Origenerator", icon=icon).prepare_launcher(
            "Origenerator", _Path(sys.executable).with_name("python.exe"))
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


def _init_windows_taskbar_identity() -> None:
    """Give Origenerator its own taskbar identity so the pinned launcher icon
    activates this window instead of spawning a second taskbar button.

    Sets the process AppUserModelID and stamps the matching ID onto the pinned
    shortcut, which is what lets Windows group them as one app. No-op off Windows.
    """
    if sys.platform != "win32":
        return
    from origenerator.win32 import (
        APP_USER_MODEL_ID,
        set_app_user_model_id,
        stamp_pinned_shortcuts,
    )
    try:
        set_app_user_model_id(APP_USER_MODEL_ID)
    except OSError:
        pass  # Non-fatal — still try to stamp the shortcut below.
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


def main():
    _warm_voice_runtimes()  # must precede the first PyQt6 import below
    _init_windows_taskbar_identity()
    _name_this_process()

    import logging

    from PyQt6.QtWidgets import QApplication

    from origenerator.config import (
        DB_PATH, STATE_DIR, COMFYUI_HOST, COMFYUI_PORT,
        COMFYUI_OUTPUT_DIR, COMFYUI_DIR, COMFYUI_LOG_DIR, THUMB_DIR, UI_STATE_PATH,
    )
    from origenerator.gui.loading_screen import LoadingScreen

    from logging.handlers import RotatingFileHandler
    log_handlers = [logging.StreamHandler()]
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_handlers.append(RotatingFileHandler(
            STATE_DIR / "origenerator.log", maxBytes=1_000_000, backupCount=2,
            encoding="utf-8",
        ))
    except OSError:
        pass  # console logging still works if the file can't be opened
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=log_handlers,
    )
    logger = logging.getLogger(__name__)
    logger.info("BUILD MARKERS: slideshow=random, voice=always-listening (Auto = voice on)")

    app = QApplication.instance() or QApplication(sys.argv)

    # The one place the stylesheet is applied, and it must be the application:
    # QToolTip popups are top-level widgets a window-level sheet never reaches,
    # so styling per-window left every tooltip on the native Windows 11 dark
    # palette — which renders them unreadable, i.e. effectively missing.
    from origenerator.gui.stylesheet import build_stylesheet
    app.setStyleSheet(build_stylesheet())

    # Show the splash before the slow imports/boot work below so the user gets
    # immediate feedback. Each phase updates its status line; app.processEvents
    # keeps the busy sweep animating while the main thread is blocked.
    loading = LoadingScreen()
    loading.show()
    _bring_to_front(loading)
    app.processEvents()

    def status(message: str) -> None:
        loading.set_status(message)
        app.processEvents()

    status("Starting ComfyUI server...")
    _ensure_comfyui_server(
        logger, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_DIR,
        on_status=status, pump_events=app.processEvents,
    )

    # A branch session (a worktree run via launch_preview_branch.vbs) is here to
    # show unlanded code, not to maintain the library — so it starts from the
    # primary install's database rather than re-scanning ComfyUI's whole history
    # into a fresh one, and skips the maintenance passes below (see
    # origenerator.branch_session).
    from origenerator.branch_session import is_branch_session, seed_branch_db
    branch_session = is_branch_session()

    status("Opening the image library...")
    if branch_session:
        from origenerator.config import project_dir
        try:
            primary_db = project_dir("origenerator") / "state" / DB_PATH.name
            if seed_branch_db(primary_db, DB_PATH):
                logger.info("Branch session: database seeded from %s", primary_db)
        except Exception as e:
            logger.warning("Branch DB seed failed (starting empty): %s", e)
    from origenerator.db import Database
    db = Database(DB_PATH)

    # Age out the recovery bin: deletions past their window are ended for good
    # and any trash folder no surviving record names is reclaimed (see
    # origenerator.recovery). A branch session sweeps nothing at all — its
    # database is a copy, so the deletions it inherited point at the *live*
    # install's held files, and both purging and restoring them from here would
    # reach into the library the live app is still showing.
    if not branch_session:
        from origenerator.branch_session import session_trash
        from origenerator import recovery
        try:
            expired = recovery.sweep(db, session_trash(STATE_DIR / "trash"))
            if expired:
                logger.info("Recovery bin: ended %d expired deletion(s)", expired)
        except Exception as e:
            logger.warning("Recovery-bin sweep failed: %s", e)

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
        # The seeded database is already maintained — every pass below ran on it
        # in the live app. Re-running them here would only slow the preview down
        # (the import scan alone reads the whole output history) and write
        # records the live install then imports as duplicates of its own.
        status("Skipping library maintenance (branch session)...")
        logger.info("Branch session: library maintenance left to the live app")
    else:
        status("Adopting branch-session results...")
        # What a preview branch generated comes home as the rows that session
        # recorded — generated, full params — before the import scan below can
        # find the bare files and reconstruct lesser "imported" rows for them.
        from origenerator.branch_session import adopt_branch_rows
        from origenerator.config import PROJECT_DIR
        try:
            adopted = adopt_branch_rows(
                db, PROJECT_DIR / ".claude" / "worktrees", COMFYUI_OUTPUT_DIR, THUMB_DIR)
            if adopted:
                logger.info("Adopted %d generations from branch sessions", adopted)
        except Exception as e:
            logger.warning("Branch-session adoption failed: %s", e)

        status("Reconnecting to running generations...")
        # Resolve any generation left mid-run by a previous session against ComfyUI
        # (finished-while-away, still-running, or gone). Runs before the import below
        # so a finalized job's output is already recorded and isn't imported twice.
        from origenerator.reconcile import reconcile_in_flight
        try:
            reconcile_in_flight(db, client, COMFYUI_OUTPUT_DIR, THUMB_DIR)
        except Exception as e:
            logger.warning("Reconcile of in-flight generations failed: %s", e)

        status("Scanning for new images...")
        from origenerator.importer import (
            backfill_input_image,
            backfill_model_and_lora_params,
            backfill_shared_thumbnails,
            backfill_unknown_workflows,
            import_comfyui_output,
            merge_video_sidecar_rows,
        )
        try:
            count = import_comfyui_output(COMFYUI_OUTPUT_DIR, db, THUMB_DIR)
            if count:
                logger.info("Imported %d existing files from ComfyUI output", count)
        except Exception as e:
            logger.warning("Import failed: %s", e)

        status("Tidying up video previews...")
        # Fold each video's metadata-PNG sidecar into one playable gallery entry.
        try:
            consolidated = merge_video_sidecar_rows(db)
            if consolidated:
                logger.info("Consolidated %d video sidecar previews", consolidated)
        except Exception as e:
            logger.warning("Sidecar consolidation failed: %s", e)

        status("Updating workflow labels...")
        # Relabel any imports that predate filename-based workflow inference.
        try:
            relabeled = backfill_unknown_workflows(db)
            if relabeled:
                logger.info("Relabelled %d previously-unknown imports", relabeled)
        except Exception as e:
            logger.warning("Workflow backfill failed: %s", e)

        status("Sorting by model and LoRA...")
        # Fill the base model and LoRA onto imports that predate reading them from
        # the embedded graph, so they nest into the gallery's model/LoRA folders.
        try:
            sorted_ = backfill_model_and_lora_params(db)
            if sorted_:
                logger.info("Backfilled model/LoRA for %d imports", sorted_)
        except Exception as e:
            logger.warning("Model/LoRA backfill failed: %s", e)

        status("Linking videos to their source images...")
        # Fill input_image onto image-to-video imports that predate reading it from
        # the embedded graph, so each video links back to the gallery image it was
        # animated from (the same link a freshly generated i2v/flf2v already carries).
        try:
            linked = backfill_input_image(db)
            if linked:
                logger.info("Backfilled source image for %d video imports", linked)
        except Exception as e:
            logger.warning("Input-image backfill failed: %s", e)

        status("Folding enhancements into their images...")
        # A standalone enhance is an upgrade of an existing image, not its own
        # generation: fold any completed image_enhance row onto its source —
        # completions that landed while the app was closed, and the rows from
        # before enhancement folded at all.
        from origenerator.gallery import fold_completed_enhancements
        try:
            fold_completed_enhancements(db)
        except Exception as e:
            logger.warning("Enhancement fold failed: %s", e)

        status("Repairing thumbnails...")
        # Re-render any thumbnail an old filename-stem collision left wrong or
        # missing, so each generation's thumbnail matches its own preview again.
        try:
            fixed = backfill_shared_thumbnails(db, COMFYUI_OUTPUT_DIR, THUMB_DIR)
            if fixed:
                logger.info("Repaired %d colliding thumbnails", fixed)
        except Exception as e:
            logger.warning("Thumbnail repair failed: %s", e)

        status("Recovering generation times...")
        # Recover how long past generations took from ComfyUI's console logs, so
        # estimates have history to draw on before any new run is timed live.
        from origenerator.log_backfill import backfill_durations_from_logs
        try:
            log_paths = sorted(COMFYUI_LOG_DIR.glob("comfyui*.log"))
            timed = backfill_durations_from_logs(db, log_paths)
            if timed:
                logger.info("Backfilled generation time for %d imports from logs", timed)
        except Exception as e:
            logger.warning("Duration backfill failed: %s", e)

        status("Restoring folder bookmarks...")
        # Heal stars and custom names whose folder key drifted after a key formula
        # change, and stamp identity onto live ones so the next change is handled
        # automatically. Runs after the backfills above — they can move a generation's
        # folder by filling in its workflow/model/LoRA — so the tree it reconciles
        # against is final.
        from origenerator.reconcile import reconcile_custom_folders, reconcile_folder_meta
        try:
            reconcile_folder_meta(db)
            # The folders the user composed by hand gather members by the same
            # keys, so they drift the same way and heal the same way.
            reconcile_custom_folders(db)
        except Exception as e:
            logger.warning("Folder bookmark reconcile failed: %s", e)

    status("Connecting to ComfyUI...")
    client.start()

    status("Building the interface...")
    from origenerator.gui.main_window import OrigeneratorWindow
    window = OrigeneratorWindow(client, db, app_state)
    window.show()

    loading.close()
    # Let the splash's closing settle before asking for the foreground: Windows
    # hands activation on from a closing window to whatever is next in the
    # Z-order, and unpumped that lands *after* the request below and undoes it.
    app.processEvents()
    _bring_to_front(window)

    exit_code = app.exec()
    client.stop()
    client.wait(3000)
    sys.exit(exit_code)
