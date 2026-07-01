import sys


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


def main():
    _init_windows_taskbar_identity()

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

    app = QApplication.instance() or QApplication(sys.argv)

    # Show the splash before the slow imports/boot work below so the user gets
    # immediate feedback. Each phase updates its status line; app.processEvents
    # keeps the busy sweep animating while the main thread is blocked.
    loading = LoadingScreen()
    loading.show()
    app.processEvents()

    def status(message: str) -> None:
        loading.set_status(message)
        app.processEvents()

    status("Starting ComfyUI server...")
    _ensure_comfyui_server(
        logger, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_DIR,
        on_status=status, pump_events=app.processEvents,
    )

    status("Opening the image library...")
    from origenerator.db import Database
    db = Database(DB_PATH)

    # Reclaim any trash left by deletes from a previous session: the in-memory
    # undo stack is empty now, so those held files are unreachable and safe to
    # clear (see GalleryActions / Trash).
    from origenerator.trash import Trash
    try:
        Trash(STATE_DIR / "trash").sweep()
    except Exception as e:
        logger.warning("Trash sweep failed: %s", e)

    status("Scanning for new images...")
    from origenerator.importer import (
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

    status("Connecting to ComfyUI...")
    from origenerator.comfyui_client import ComfyUIClient
    client = ComfyUIClient(host=COMFYUI_HOST, port=COMFYUI_PORT)
    client.start()

    status("Building the interface...")
    from origenerator.app_state import AppState
    from origenerator.gui.main_window import OrigeneratorWindow
    window = OrigeneratorWindow(client, db, AppState(UI_STATE_PATH))
    window.show()

    loading.close()

    exit_code = app.exec()
    client.stop()
    client.wait(3000)
    sys.exit(exit_code)
