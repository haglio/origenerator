# ruff: noqa: PLC0415
# Imports below are late on purpose: QT_SCALE_FACTOR must be set before Qt's platform plugin starts, and the voice runtimes load before Qt.
from __future__ import annotations

import contextlib
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from app_support import origenerator_handoff
from app_support.process_identity import ProcessNamer
from shared_ui.preview import Preview, taskbar_identity, window_title

from origenerator.boot_passes import MAINTENANCE, Library, run_maintenance, without_comfyui
from origenerator.branch_session import LAUNCHER, shown_as

_CLIENT_ID_KEY = "comfyui_client_id"


def resolve_comfyui_client_id(app_state) -> str:
    """ComfyUI sends a running prompt's messages only to the client id that submitted it."""
    stored = app_state.get(_CLIENT_ID_KEY)
    if isinstance(stored, str) and stored:
        return stored
    client_id = str(uuid.uuid4())
    app_state.set(_CLIENT_ID_KEY, client_id)
    app_state.save()
    return client_id


CHECKOUT = Path(__file__).resolve().parent.parent


def _the_preview_on_the_taskbar(preview: Preview | None, state_dir: Path):
    if preview is None:
        return None
    from app_support.win32 import TaskbarApp
    from shared_ui.preview_icon_pil import icon_file

    from origenerator.fun_time_mode import WINDOW_TITLE
    return TaskbarApp(name=window_title(WINDOW_TITLE, preview),
                      icon=icon_file(CHECKOUT / "icon.ico", preview, state_dir),
                      relaunch=f'wscript.exe "{CHECKOUT / LAUNCHER}"')


def _taskbar_identity(app, fun_time, preview: Preview | None, state_dir: Path):
    if sys.platform != "win32":
        return None
    from app_support.win32 import described_taskbar_app, dress_window

    from origenerator.gui.taskbar_identity import TaskbarIdentity
    from origenerator.win32 import APP_USER_MODEL_ID
    taskbar = TaskbarIdentity(app, taskbar_identity(APP_USER_MODEL_ID, preview),
                              _the_preview_on_the_taskbar(preview, state_dir),
                              dress=dress_window, described=described_taskbar_app)
    if fun_time is not None and fun_time.taskbar_identity:
        taskbar.join(fun_time.taskbar_identity)
    return taskbar


def _name_this_process() -> None:
    ProcessNamer("Origenerator", icon=CHECKOUT / "icon.ico").name_this_process(
        "Origenerator", interpreter="python.exe")


def _init_windows_taskbar_identity(identity: str | None, preview: Preview | None) -> None:
    """Windows groups the pinned shortcut and the window as one app only when both carry the same AppUserModelID."""
    if sys.platform != "win32":
        return
    from app_support.win32 import set_app_user_model_id, stamp_pinned_shortcuts

    from origenerator.win32 import APP_USER_MODEL_ID
    with contextlib.suppress(OSError):
        set_app_user_model_id(identity or taskbar_identity(APP_USER_MODEL_ID, preview))
    if identity is None:
        import logging

        log = logging.getLogger(__name__)
        for pin, refusal in stamp_pinned_shortcuts(APP_USER_MODEL_ID, ["Origenerator"]).items():
            if refusal is None:
                log.info("Stamped AppUserModelID on %s", pin)
            else:
                log.warning("Could not stamp AppUserModelID on %s: %s", pin, refusal)


def _warm_voice_runtimes() -> None:
    """ctranslate2 and onnxruntime fail with an access violation or DLL init error when imported after Qt; a broken install raises OSError."""
    for module in ("onnxruntime", "ctranslate2"):
        with contextlib.suppress(Exception):
            __import__(module)


def _configure_logging(state_dir: Path):
    import logging

    from app_support.logging_utils import configure_logging, install_exception_logging

    from origenerator.qt_messages import install_qt_message_logging

    try:
        configure_logging("", state_dir / "origenerator.log", console=True)
    except OSError:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_qt_message_logging()
    logger = logging.getLogger(__name__)
    install_exception_logging(logger)
    return logger


def _arm_the_crash_log(state_dir: Path, logger):
    import faulthandler
    from datetime import UTC, datetime

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        stream = open(  # noqa: SIM115
            state_dir / "origenerator_crash.log", "a", encoding="utf-8")
        launched = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
        stream.write(f"\n=== launched {launched} ===\n")
        stream.flush()
        faulthandler.enable(file=stream, all_threads=True)
    except Exception as e:
        logger.warning("Crash log unavailable: %s", e)
        return None
    return stream


WAITING_FOR_THE_OTHER_COPY = "Waiting for the other copy to finish closing..."
STARTING_THE_SERVER = "Starting ComfyUI server..."
OPENING_THE_LIBRARY = "Opening the image library..."
CONNECTING = "Connecting to ComfyUI..."
BUILDING_THE_INTERFACE = "Building the interface..."


def boot_steps(maintenance) -> tuple[tuple[str, float], ...]:
    return (
        (STARTING_THE_SERVER, 4.0),
        (OPENING_THE_LIBRARY, 1.0),
        *((boot_pass.status, 0.3) for boot_pass in maintenance if boot_pass.status),
        (CONNECTING, 0.5),
        (BUILDING_THE_INTERFACE, 3.0),
    )


def _say_where_the_window_comes_up(fun_time, ui_state_path: Path):
    from app_support.loading_screen import meeting_place

    from origenerator.app_state import AppState
    from origenerator.gui.window_monitor import GEOMETRY_KEY, the_window_saved_in

    next_launch = None if fun_time is not None else meeting_place(os.environ)
    if next_launch is not None:
        next_launch.say_where_the_app_comes_up(the_window_saved_in(AppState(ui_state_path).get(GEOMETRY_KEY)))
    return next_launch


def _open_the_loading(fun_time, app, logger, preview, taskbar):
    from origenerator.gui.loading_screen import Loading, loading_screen

    if fun_time is not None:
        return Loading(app, logger, None)
    app_id, button = (None, None) if taskbar is None else taskbar.wearing
    screen = loading_screen(CHECKOUT / "icon.ico", preview, boot_steps(MAINTENANCE),
                            app_id=app_id, taskbar=button)
    return Loading(app, logger, screen)


def _build_window(client, library, app_state, boot, next_launch):
    from origenerator.gui.core import Core, Launch

    window = Core(client, library.db, app_state, fun_time=boot.fun_time,
                  launch=Launch(boot.preview, boot.taskbar, next_launch), inbox=library.inbox)
    if boot.fun_time is not None and not boot.fun_time.in_a_headset:
        window.showMinimized()
    return window


def _put_away_unseen(window, app, crash_log) -> None:
    window.close()
    freeze_watch = None
    if crash_log is not None:
        from origenerator.freeze_watch import watch_the_window
        freeze_watch = watch_the_window(app, crash_log)
        freeze_watch.end_the_process_if_the_close_sticks()
    _run_the_loop_only_to_quit(app)
    _hand_comfyui_what_runs_while_closed(window, freeze_watch)


def _hand_comfyui_what_runs_while_closed(window, freeze_watch) -> None:
    if freeze_watch is not None:
        freeze_watch.end_the_process_if_the_hand_over_sticks()
    window.hand_comfyui_what_runs_while_closed()
    if freeze_watch is not None:
        freeze_watch.end_the_process_if_the_close_sticks()


def _run_the_loop_only_to_quit(app) -> None:
    from origenerator.gui.deferred import defer

    defer(app, app.quit)
    app.exec()


def _disconnect(client) -> None:
    client.stop()
    client.wait(3000)


def _watch_for_fun_time(window, state_dir, library_state_dir):
    from origenerator.gui.fun_time_watch import FunTimeWatch

    watch = FunTimeWatch(state_dir, take_over=window.become_hosted,
                         device_claimed=window.the_session_has_the_device,
                         showing_on=window.slideshow_showing_on,
                         library_state_dir=library_state_dir)
    window.handed_back.connect(watch.renew)
    return watch


def _refuse_an_incomplete_overlay(missing: tuple[str, ...], fun_time) -> int:
    from origenerator.content import EXAMPLE_CONTENT, LOCAL_CONTENT

    message = (
        f"{LOCAL_CONTENT} is missing {len(missing)} key(s) this version needs:\n\n"
        + "\n".join(f"    {key}" for key in missing)
        + f"\n\nCopy them from {EXAMPLE_CONTENT.name}. A key can be left empty "
          "to switch that feature off."
    )
    print(f"Origenerator: {message}", file=sys.stderr)
    if fun_time is None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Origenerator: incomplete content overlay", message)
    return 1


def _refuse_a_library_of_its_own(checkout: Path, fun_time) -> int:
    message = (
        f"This copy runs from {checkout}, which is not the production Origenerator's "
        "folder, and it was not started as a preview, so it would open a gallery of "
        "its own beside yours. It does not start. A branch's copy starts with the "
        "launch_preview_branch.vbs in its folder."
    )
    print(f"Origenerator: {message}", file=sys.stderr)
    if fun_time is None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Origenerator: not the production copy", message)
    return 1


def _say_what_evolver_no_longer_agrees_with(fun_time) -> None:
    from origenerator import evolver_agreement

    said = evolver_agreement.disagreements(
        evolver_agreement.our_side(), evolver_agreement.evolver_checkout())
    if not said:
        return
    message = ("Origenerator and Evolver no longer agree about the hand-off, so a "
               "sent video may arrive where nothing reads it:\n\n"
               + "\n".join(f"    {line}" for line in said))
    print(f"Origenerator: {message}", file=sys.stderr)
    if fun_time is None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, "Origenerator: Evolver has moved", message)


@dataclass
class Boot:
    app: object
    fun_time: object
    preview: Preview | None
    taskbar: object
    logger: object
    state_dir: Path
    library_state_dir: Path
    loading: object = None
    claim: object = None
    crash_log: object = None
    clicked_toasts: object = None
    watch: object = None
    freeze_watch: object = None

    @property
    def waits_for_comfyui(self) -> bool:
        return self.fun_time is None

    def start_comfyui_first(self) -> None:
        if not self.waits_for_comfyui:
            return
        from origenerator import comfyui_launcher
        from origenerator.config import COMFYUI_DIR, COMFYUI_HOST, COMFYUI_PORT

        self.say(STARTING_THE_SERVER)
        comfyui_launcher.ensure_comfyui_server(
            self.logger, comfyui_launcher.Address(COMFYUI_HOST, COMFYUI_PORT), COMFYUI_DIR,
            on_status=self.say, pump_events=self.app.processEvents,
        )

    def maintenance(self):
        return MAINTENANCE if self.waits_for_comfyui else without_comfyui(MAINTENANCE)

    def bring_comfyui_up_behind(self, library: Library, window) -> None:
        if self.waits_for_comfyui:
            return
        from origenerator.gui.comfyui_behind import bring_comfyui_up_behind_the_window

        bring_comfyui_up_behind_the_window(library, self.logger, owner=self.app,
                                           then=window.core_is_ready)

    def say(self, step: str) -> None:
        if self.loading is None:
            self.loading = _open_the_loading(self.fun_time, self.app, self.logger,
                                             self.preview, self.taskbar)
        self.loading.say(step)

    def stop_if_canceled(self) -> None:
        self.loading.stop_if_canceled()

    def done(self) -> None:
        if self.loading is not None:
            self.loading.done()

    def claim_the_library(self, copies) -> int | None:
        from origenerator.app_link import made_for_a_click
        from origenerator.single_instance import say_another_copy_is_running

        self.claim = copies.claim_the_library()
        if self.claim is None and self.fun_time is None:
            if copies.one_is_closing():
                self.logger.info("Another copy is closing; waiting for it to let go of the library")
                self.say(WAITING_FOR_THE_OTHER_COPY)
                self.claim = copies.claim_the_library_once_the_closing_one_lets_go()
            elif made_for_a_click():
                self.logger.info("Another copy of Origenerator is already running; "
                                 "the click is left to it")
                return 0
        if self.claim is None and self.fun_time is None:
            self.done()
            self.logger.warning("Another copy of Origenerator is already running; not starting")
            say_another_copy_is_running()
            return 1
        if self.claim is not None:
            self.claim.closes_with(self.app)
        return None

    def offer_to_fun_time(self) -> None:
        if self.fun_time is None:
            origenerator_handoff.offer_this_process(self.state_dir, self.library_state_dir,
                                                    starting=True)

    def arm_the_crash_log(self) -> None:
        self.crash_log = _arm_the_crash_log(self.state_dir, self.logger)

    def listen_for_clicked_toasts(self, checkout: Path) -> None:
        from origenerator.gui.link_listener import LinkListener

        self.clicked_toasts = LinkListener(checkout=checkout, parent=self.app)

    def show(self, window) -> None:
        if self.fun_time is None:
            self.watch = _watch_for_fun_time(window, self.state_dir, self.library_state_dir)
        still_offered = self.watch is not None and self.watch.stands_its_offer()
        if still_offered:
            window.show()
        self.done()
        if still_offered:
            from shared_ui.foreground import bring_to_front
            bring_to_front(window)
        self.clicked_toasts.answer_with(window.go_to_generation)

    def run(self) -> int:
        from origenerator.freeze_watch import watch_the_window

        self.freeze_watch = (None if self.crash_log is None
                             else watch_the_window(self.app, self.crash_log))
        return self.app.exec()

    def cancel(self, window, client) -> int:
        self.logger.info("Loading canceled from the loading screen")
        if window is not None:
            _put_away_unseen(window, self.app, self.crash_log)
        _disconnect(client)
        origenerator_handoff.withdraw_the_offer(self.state_dir, self.library_state_dir)
        if self.claim is not None:
            self.claim.let_go()
        self.done()
        return 0

    def close(self, window, client) -> None:
        if self.watch is not None:
            self.watch.withdraw()
        _hand_comfyui_what_runs_while_closed(window, self.freeze_watch)
        _disconnect(client)
        if self.claim is not None:
            self.claim.let_go()


def _check_the_launch(logger) -> int:
    from origenerator import app_state, comfyui_client, db  # noqa: F401
    from origenerator.gui import core  # noqa: F401

    logger.info("Launch check passed (%s)", sys.executable)
    return 0


def main(argv: list[str] | None = None) -> int:
    from origenerator.fun_time_mode import parse_app_args

    app_args = parse_app_args(sys.argv[1:] if argv is None else argv)
    fun_time = app_args.fun_time
    if fun_time is not None:
        from origenerator.ui_scale import apply_room_scale
        apply_room_scale(in_a_headset=fun_time.in_a_headset)
    _warm_voice_runtimes()
    preview = shown_as(CHECKOUT)
    _init_windows_taskbar_identity(fun_time and fun_time.taskbar_identity, preview)
    _name_this_process()

    from shared_ui.application import application

    with application(sys.argv[:1]) as app:
        return _boot_and_run(app, app_args, preview)


def _open_the_library(boot, client) -> Library:
    from origenerator.config import COMFYUI_LOG_DIR, DB_PATH, OUTPUT_PLACES, THUMB_DIR
    from origenerator.db import Database
    from origenerator.evolver_export import default_inbox
    from origenerator.inflight import in_flight_at
    from origenerator.warm_gun_records import PhoneRecords

    boot.say(OPENING_THE_LIBRARY)
    boot.logger.info("Library: %s", DB_PATH)
    db = Database(DB_PATH)
    library = Library(db=db, client=client, places=OUTPUT_PLACES, thumb_dir=THUMB_DIR,
                      log_dir=COMFYUI_LOG_DIR, inbox=default_inbox(), in_flight=in_flight_at(db))
    run_maintenance(library, boot.maintenance(), boot.say, boot.logger)
    PhoneRecords.of_this_library(db, preview=boot.preview is not None).watch()
    return library


def _boot_and_run(app, app_args, preview) -> int:
    fun_time = app_args.fun_time
    from origenerator.content import missing_overlay_keys
    missing = missing_overlay_keys()
    if missing:
        return _refuse_an_incomplete_overlay(missing, fun_time)

    from origenerator import config
    from origenerator.comfyui_folders import COMFYUI_FOLDERS
    from origenerator.config import (
        COMFYUI_HOST,
        COMFYUI_PORT,
        LIBRARY_STATE_DIR,
        PRODUCTION_CHECKOUT,
        STATE_DIR,
        UI_STATE_PATH,
    )

    if config.STARTS_A_LIBRARY_OF_ITS_OWN:
        return _refuse_a_library_of_its_own(config.PROJECT_DIR, fun_time)

    logger = _configure_logging(STATE_DIR)
    _say_what_evolver_no_longer_agrees_with(fun_time)
    from origenerator.gui.stylesheet import dress_application
    dress_application(app, preview)
    taskbar = _taskbar_identity(app, fun_time, preview, STATE_DIR)
    if app_args.check_launch:
        return _check_the_launch(logger)

    next_launch = _say_where_the_window_comes_up(fun_time, UI_STATE_PATH)
    from origenerator.single_instance import Copies
    boot = Boot(app, fun_time, preview, taskbar, logger, STATE_DIR, LIBRARY_STATE_DIR)
    refused = boot.claim_the_library(Copies(LIBRARY_STATE_DIR))
    if refused is not None:
        return refused
    boot.offer_to_fun_time()
    boot.arm_the_crash_log()
    boot.listen_for_clicked_toasts(PRODUCTION_CHECKOUT)

    from origenerator.app_state import AppState
    app_state = AppState(UI_STATE_PATH)

    from origenerator.comfyui_client import ComfyUIClient
    client = ComfyUIClient(
        host=COMFYUI_HOST, port=COMFYUI_PORT,
        client_id=resolve_comfyui_client_id(app_state),
        folders=COMFYUI_FOLDERS,
    )

    from origenerator.gui.loading_screen import LoadingCanceled
    window = None
    try:
        boot.start_comfyui_first()
        library = _open_the_library(boot, client)

        boot.say(CONNECTING)
        client.start()

        boot.say(BUILDING_THE_INTERFACE)
        window = _build_window(client, library, app_state, boot, next_launch)
        boot.stop_if_canceled()
    except LoadingCanceled:
        return boot.cancel(window, client)

    boot.bring_comfyui_up_behind(library, window)
    boot.show(window)
    exit_code = boot.run()
    boot.close(window, client)
    from origenerator.landed_while_away import hand_over_what_is_in_flight
    from origenerator.win32 import APP_USER_MODEL_ID
    hand_over_what_is_in_flight(library.db, taskbar_identity(APP_USER_MODEL_ID, preview))
    return exit_code
