# ruff: noqa: PLC0415 -- inside the function, so naming this module costs nothing
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def taskbar_identity(title: str, preview) -> str:
    from shared_ui.preview import taskbar_identity as named_for

    from origenerator.win32 import APP_USER_MODEL_ID

    return named_for(f"{APP_USER_MODEL_ID}.{title.title().replace(' ', '')}",
                     preview)


def taskbar_app(title: str, launcher: str, preview):
    from app_support.win32 import TaskbarApp
    from shared_ui.preview_icon_pil import icon_file

    from origenerator.config import PROJECT_DIR, STATE_DIR
    # Windows: a taskbar button told neither wears the icon of the python that started the window
    # whenever the window is too busy to answer for itself.
    return TaskbarApp(name=f"Origenerator — {title}",
                      icon=icon_file(PROJECT_DIR / "icon.ico", preview, STATE_DIR),
                      relaunch=f'wscript.exe "{PROJECT_DIR / launcher}"')


def _claim_the_taskbar(identity: str) -> None:
    if sys.platform != "win32":
        return
    from app_support.win32 import set_app_user_model_id

    try:
        set_app_user_model_id(identity)
    except OSError as refused:
        logger.warning("Could not claim %s on the taskbar: %s", identity, refused)


def _dress_the_taskbar_button(app, title: str, launcher: str, preview) -> None:
    if sys.platform != "win32":
        return
    from app_support.win32 import described_taskbar_app, dress_window

    from origenerator.gui.taskbar_identity import TaskbarIdentity
    TaskbarIdentity(app, taskbar_identity(title, preview),
                    taskbar_app(title, launcher, preview),
                    dress=dress_window, described=described_taskbar_app)


def open_on_its_own(title: str, build, *, launcher: str, find_missing_overlay_keys=None) -> int:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication(sys.argv[:1])

    if find_missing_overlay_keys is None:
        from origenerator.content import missing_overlay_keys as find_missing_overlay_keys
    missing = find_missing_overlay_keys()
    if missing:
        QMessageBox.critical(None, title,
                             "The content overlay is missing: " + ", ".join(missing))
        return 1

    from origenerator.branch_session import shown_as
    from origenerator.config import PROJECT_DIR
    preview = shown_as(PROJECT_DIR)
    _claim_the_taskbar(taskbar_identity(title, preview))
    _dress_the_taskbar_button(app, title, launcher, preview)

    from origenerator.gui.stylesheet import dress_application
    dress_application(app, preview)

    # Held in a local: PyQt collected the window handed straight to show_or_say before anything could run.
    built = build()
    return 0 if show_or_say(title, built) else app.exec()


def show_or_say(title: str, built, *, parent=None) -> bool:
    from PyQt6.QtWidgets import QMessageBox

    if isinstance(built, str):
        QMessageBox.information(parent, title, built)
        return True
    built.showMaximized()
    return False
