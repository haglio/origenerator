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


def main():
    _set_windows_app_user_model_id()

    from PyQt6.QtWidgets import QApplication

    import logging

    from origenerator.comfyui_client import ComfyUIClient
    from origenerator.config import DB_PATH, COMFYUI_HOST, COMFYUI_PORT, COMFYUI_OUTPUT_DIR, THUMB_DIR
    from origenerator.db import Database
    from origenerator.gui.main_window import OrigeneratorWindow
    from origenerator.importer import import_comfyui_output

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger(__name__)

    app = QApplication.instance() or QApplication(sys.argv)

    db = Database(DB_PATH)

    # Import existing ComfyUI output on launch
    try:
        count = import_comfyui_output(COMFYUI_OUTPUT_DIR, db, THUMB_DIR)
        if count:
            logger.info("Imported %d existing files from ComfyUI output", count)
    except Exception as e:
        logger.warning("Import failed: %s", e)

    client = ComfyUIClient(host=COMFYUI_HOST, port=COMFYUI_PORT)
    client.start()

    window = OrigeneratorWindow(client, db)
    window.show()

    exit_code = app.exec()
    client.stop()
    client.wait(3000)
    sys.exit(exit_code)
