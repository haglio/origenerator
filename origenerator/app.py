import sys

ORIGENERATOR_APP_USER_MODEL_ID = "FunTime.Origenerator"


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        set_app_id(ORIGENERATOR_APP_USER_MODEL_ID)
    except Exception:
        pass


def _ensure_comfyui_server(logger, host, port, comfyui_dir):
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
        result = server.start(base_dir=comfyuiapp_dir)
        if result.started:
            logger.info("ComfyUI server started (PID %s)", result.pid)
        elif result.error:
            logger.warning("ComfyUI server failed to start: %s", result.error)
        else:
            logger.info("ComfyUI server was already running")
    except Exception as e:
        logger.warning("Failed to start ComfyUI server: %s", e)


def main():
    _set_windows_app_user_model_id()

    from PyQt6.QtWidgets import QApplication

    import logging

    import logging
    from pathlib import Path

    from origenerator.comfyui_client import ComfyUIClient
    from origenerator.config import (
        DB_PATH, COMFYUI_HOST, COMFYUI_PORT,
        COMFYUI_OUTPUT_DIR, COMFYUI_DIR, THUMB_DIR,
    )
    from origenerator.db import Database
    from origenerator.gui.main_window import OrigeneratorWindow
    from origenerator.importer import backfill_unknown_workflows, import_comfyui_output

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger(__name__)

    app = QApplication.instance() or QApplication(sys.argv)

    # Ensure ComfyUI server is running
    _ensure_comfyui_server(logger, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_DIR)

    db = Database(DB_PATH)

    # Import existing ComfyUI output on launch
    try:
        count = import_comfyui_output(COMFYUI_OUTPUT_DIR, db, THUMB_DIR)
        if count:
            logger.info("Imported %d existing files from ComfyUI output", count)
    except Exception as e:
        logger.warning("Import failed: %s", e)

    # Relabel any imports that predate filename-based workflow inference
    try:
        relabeled = backfill_unknown_workflows(db)
        if relabeled:
            logger.info("Relabelled %d previously-unknown imports", relabeled)
    except Exception as e:
        logger.warning("Workflow backfill failed: %s", e)

    client = ComfyUIClient(host=COMFYUI_HOST, port=COMFYUI_PORT)
    client.start()

    window = OrigeneratorWindow(client, db)
    window.show()

    exit_code = app.exec()
    client.stop()
    client.wait(3000)
    sys.exit(exit_code)
