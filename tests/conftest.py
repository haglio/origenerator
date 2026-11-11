from __future__ import annotations

import contextlib
import errno
import gc
import itertools
import json
import os
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import winsound
from pathlib import Path

import pytest
from app_support import win32 as windows_api
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, Qt, pyqtSignal, qInstallMessageHandler
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from origenerator import (
    card_claim,
    config,
    enhance_presets,
    gallery,
    graphics_card,
    osr2_driver,
    osr2_motion_driver,
    running_ahead,
    toast_raising,
)
from origenerator.gui import (
    gallery_view,
    generation_job,
    job_queue,
    omnipause,
    osr2_controls,
    toasts,
    voice_router,
)
from origenerator.gui.combine_controller import CombineController
from origenerator.gui.gallery_view import GalleryView
from origenerator.workflows import detail_parts

pytest_plugins = ("shared_ui.testing",)

graphics_card.NVIDIA_SMI = ("nvidia-smi-the-suite-never-runs",)
card_claim.CLAIM = Path(os.environ["ORIGENERATOR_STATE_DIR"]) / "graphics_card_claim.json"


@pytest.fixture(autouse=True)
def _unscaled_between_tests():
    """QT_SCALE_FACTOR is a process-global environment variable that Qt reads per widget, so a test that scales the app would scale every test after it."""
    before = os.environ.get("QT_SCALE_FACTOR")
    try:
        yield
    finally:
        if os.environ.get("QT_SCALE_FACTOR") != before:
            from origenerator import ui_scale  # noqa: PLC0415 (after Qt is up)
            ui_scale.draw_at(1.0)
        if before is None:
            os.environ.pop("QT_SCALE_FACTOR", None)
        else:
            os.environ["QT_SCALE_FACTOR"] = before

# Qt reads this as the QApplication is created, so it is set before pytest-qt's qapp fixture makes one.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


ARCH_TENSOR_NAMES = {
    "sdxl": ["conditioner.embedders.0.transformer.x", "model.diffusion_model.input_blocks.0.y"],
    "sd15": ["cond_stage_model.transformer.x", "model.diffusion_model.input_blocks.0.y"],
    "flux": ["double_blocks.0.img_attn.qkv.weight", "single_blocks.0.linear1.weight"],
    "qwen": ["transformer_blocks.0.attn.to_q.weight", "txt_norm.weight"],
    "wan": ["blocks.0.self_attn.q.weight", "patch_embedding.weight"],
    "wan_t2v": ["blocks.0.self_attn.q.weight", "patch_embedding.weight"],
    "wan_fun_control": ["blocks.0.self_attn.q.weight", "patch_embedding.weight",
                        "ref_conv.weight"],
    "wan_s2v": ["audio_injector.injector.0.k.weight", "blocks.0.self_attn.q.weight",
                "patch_embedding.weight"],
    "wan_animate": ["blocks.0.self_attn.q.weight", "pose_patch_embedding.weight",
                    "patch_embedding.weight"],
    "ltx": ["patchify_proj.weight", "transformer_blocks.0.attn1.to_q.weight"],
    "krea2": ["first.weight", "blocks.0.attn.wq.weight", "txtfusion.projector.weight"],
}
_ARCH_TENSOR_SHAPES = {"wan_t2v": {"patch_embedding.weight": [5120, 16, 1, 2, 2]}}


class ModelTree:
    def __init__(self, root):
        self.root = root

    def add_bytes(self, category, name, body):
        path = self.root / "models" / category / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def add(self, category, name, *, arch=None, lora=False, metadata=None):
        path = self.root / "models" / category / name
        path.parent.mkdir(parents=True, exist_ok=True)
        names = list(ARCH_TENSOR_NAMES[arch]) if arch else ["unknown.weight"]
        if lora:
            names = [f"{name}.lora_A.weight" for name in names]
        shapes = _ARCH_TENSOR_SHAPES.get(arch, {})
        header = json.dumps({
            **({"__metadata__": metadata} if metadata is not None else {}),
            **{n: {"dtype": "F16", "shape": shapes.get(n, [1]), "data_offsets": [0, 2]}
               for n in names},
        }).encode()
        path.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
        return path


@pytest.fixture
def sheet_put_back_for_later_tests(qapp):
    prior = qapp.styleSheet()
    yield qapp
    qapp.setStyleSheet(prior)


@pytest.fixture
def installed_models(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    return ModelTree(tmp_path)


def _kept_by_stem_in(tmp_path, monkeypatch, path_name: str):
    path = tmp_path / f"{path_name}.json"
    monkeypatch.setattr(config, path_name, path)

    def write(kept: dict) -> None:
        path.write_text(json.dumps(kept), encoding="utf-8")

    return write


@pytest.fixture
def titled_models(tmp_path, monkeypatch):
    return _kept_by_stem_in(tmp_path, monkeypatch, "MODEL_TITLES_PATH")


@pytest.fixture
def worded_loras(tmp_path, monkeypatch):
    return _kept_by_stem_in(tmp_path, monkeypatch, "TRIGGER_WORDS_PATH")


@pytest.fixture
def recorded_base_models(tmp_path, monkeypatch):
    return _kept_by_stem_in(tmp_path, monkeypatch, "BASE_MODELS_PATH")


@pytest.fixture
def described_models(tmp_path, monkeypatch):
    return _kept_by_stem_in(tmp_path, monkeypatch, "MODEL_DESCRIPTIONS_PATH")


class FakeCommandAndRequestListener(QObject):
    error = pyqtSignal(str)
    heard = pyqtSignal(str)
    request = pyqtSignal(object)

    def __init__(self, *, command_matcher=None, bare_matcher=None, dictation=None,
                 phrases=()):
        super().__init__()
        self.commands_on = False
        self._matcher = command_matcher
        self._bare_matcher = bare_matcher
        self._dictation = dictation
        self._execute = None

    def start_commands(self, execute):
        self.commands_on = True
        self._execute = execute

    def stop_commands(self):
        self.commands_on = False
        self._execute = None

    def close(self):
        self.stop_commands()

    def speak_command(self, text):
        if not self.commands_on:
            return None
        matched = self._bare_matcher(text) if self._bare_matcher else None
        if matched is None and self._matcher is not None:
            matched = self._matcher(text)
        if matched is not None:
            self._execute(matched)
        return matched

    def bare_command(self, text):
        collecting = self._dictation is not None and self._dictation.listening
        if collecting or self._bare_matcher is None:
            return None
        return self._bare_matcher(text)

    def speak(self, text):
        collecting = self._dictation is not None and self._dictation.listening
        if not collecting and self.commands_on and self._bare_matcher is not None:
            bare = self._bare_matcher(text)
            if bare is not None:
                self._execute(bare)
                return bare
        spoken = self.push_dictation(text)
        if spoken is not None:
            self.request.emit(spoken)
            return spoken
        return self.speak_command(text)

    def push_dictation(self, text, spoken_at=None):
        return (self._dictation.push(text, spoken_at=spoken_at)
                if self._dictation is not None else None)

    @property
    def taking_a_request(self):
        return self._dictation is not None and self._dictation.listening

    def drop_the_request(self):
        if self._dictation is not None:
            self._dictation.reset()


class FakeHearing(QObject):
    said = pyqtSignal(str, float)
    failed = pyqtSignal(str)

    def __init__(self, says="no hat"):
        super().__init__()
        self.says = says
        self.started = False
        self.stopped = False
        self.closed = False

    def hear(self, spoken_at=0.0):
        self.said.emit(self.says, spoken_at)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.stop()
        self.closed = True


def keep_the_microphone_shut(setattr) -> None:
    setattr(voice_router, "CommandAndRequestListener", FakeCommandAndRequestListener)


@pytest.fixture(autouse=True)
def _no_real_mic(monkeypatch):
    keep_the_microphone_shut(monkeypatch.setattr)


def refuse_the_comfyui_on_this_machine(setattr) -> None:
    real_urlopen = urllib.request.urlopen
    llm = urllib.parse.urlsplit(config.LOCAL_LLM_BASE_URL)
    refused = {(config.COMFYUI_HOST, config.COMFYUI_PORT), (llm.hostname, llm.port)}

    def urlopen(url, *args, **kwargs):
        target = urllib.parse.urlsplit(getattr(url, "full_url", url))
        if (target.hostname, target.port) in refused:
            raise urllib.error.URLError(ConnectionRefusedError(
                errno.ECONNREFUSED, "the suite never reaches a service on this machine"))
        return real_urlopen(url, *args, **kwargs)

    setattr(urllib.request, "urlopen", urlopen)


@pytest.fixture(autouse=True, scope="session")
def _never_reach_the_comfyui_on_this_machine():
    with pytest.MonkeyPatch.context() as patch:
        refuse_the_comfyui_on_this_machine(patch.setattr)
        yield


def start_no_comfyui_on_this_machine(setattr) -> None:
    setattr(job_queue, "BRING_UP_COMFYUI", None)


@pytest.fixture(autouse=True, scope="session")
def _never_start_the_comfyui_on_this_machine():
    with pytest.MonkeyPatch.context() as patch:
        start_no_comfyui_on_this_machine(patch.setattr)
        yield


def keep_off_the_device(setattr) -> None:
    class _NoDevice:
        def want(self, wanted): pass
        def ask(self, verb): pass
        def send_position(self, pos, interval_ms): pass
        def close(self): pass

    class _NoTicker:
        def __init__(self, tick, interval_s, **_kw): pass
        def start(self): pass
        def stop(self): pass

    setattr(osr2_driver, "Osr2Broker", lambda *a, **k: _NoDevice())
    setattr(osr2_motion_driver, "Osr2Broker", lambda *a, **k: _NoDevice())
    setattr(osr2_motion_driver, "_TickThread", _NoTicker)
    the_device_is_there = osr2_controls.osr2.osr2_device.Osr2Mode.CONTROLLED
    setattr(osr2_controls.osr2, "device_mode", lambda **_kw: the_device_is_there)
    setattr(osr2_controls.osr2, "device_trouble", lambda **_kw: None)
    setattr(osr2_controls.osr2, "broker_running", lambda **_kw: True)
    setattr(osr2_controls.osr2, "press_the_broker", lambda **_kw: None)


def finish_every_video_on_the_tests_own_thread(setattr) -> None:
    setattr(generation_job, "run_off_thread", lambda work, done, *, owner: done(work()))


@pytest.fixture(autouse=True)
def _never_take_the_real_device(monkeypatch):
    keep_off_the_device(monkeypatch.setattr)
    finish_every_video_on_the_tests_own_thread(monkeypatch.setattr)


def keep_out_of_windows(setattr) -> None:
    setattr(windows_api, "dress_window", lambda *_a, **_kw: None)
    setattr(toasts, "register_toast_identity", lambda *_a, **_kw: None)
    setattr(toasts, "register_link_handler", lambda *_a, **_kw: None)
    setattr(toast_raising, "show", lambda *_a, **_kw: None)
    setattr(toast_raising, "take_back", lambda *_a, **_kw: None)


@pytest.fixture(scope="session")
def _a_folder_for_each_test(tmp_path_factory):
    run = tmp_path_factory.mktemp("each_test")
    return (run / str(number) for number in itertools.count())


@pytest.fixture
def _this_tests_own_folder(_a_folder_for_each_test) -> Path:
    folder = next(_a_folder_for_each_test)
    folder.mkdir()
    return folder


@pytest.fixture(autouse=True)
def _never_name_this_app_to_the_real_windows(monkeypatch, _this_tests_own_folder):
    appdata = _this_tests_own_folder / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    keep_out_of_windows(monkeypatch.setattr)


@pytest.fixture(autouse=True)
def _never_take_a_video_out_of_the_real_kino(monkeypatch, _this_tests_own_folder):
    kino = _this_tests_own_folder / "kino"
    monkeypatch.setattr(gallery_view, "KINO_UPSCALES_DIR", kino / "2D" / "AI")
    monkeypatch.setattr(gallery_view, "KINO_TRASH_DIR", kino / "trash")


@pytest.fixture(autouse=True)
def _never_take_a_video_out_of_the_real_genau(monkeypatch, _this_tests_own_folder):
    monkeypatch.setattr(gallery_view, "GENAU_DIR", _this_tests_own_folder / "genau")


@pytest.fixture(autouse=True)
def _never_ask_the_real_evolver_to_delete_anything(monkeypatch):
    monkeypatch.setattr(gallery_view, "delete_through_evolver", lambda _videos: None)


@pytest.fixture(autouse=True)
def _never_bring_a_real_record_into_a_tests_gallery(monkeypatch):
    monkeypatch.setattr(gallery_view.outside_videos, "bring_in_one", lambda *_args, **_kw: False)





def keep_silent(setattr) -> list:
    sounded = []
    setattr(winsound, "MessageBeep", sounded.append)
    return sounded


@pytest.fixture(autouse=True)
def alert_sounds(monkeypatch):
    return keep_silent(monkeypatch.setattr)


def keep_the_run_at_its_own_priority(setattr) -> None:
    setattr(running_ahead, "_THIS_APP", running_ahead.AheadWhilePlaying(contextlib.nullcontext))


@pytest.fixture(autouse=True)
def _never_raise_the_runs_priority(monkeypatch):
    keep_the_run_at_its_own_priority(monkeypatch.setattr)


def refuse_the_dialogs_nobody_can_answer(setattr) -> None:
    """A Qt offscreen modal dialog spins a nested event loop nobody can end, so the run would hang instead of failing."""
    def refuse(name):
        def blocked(*_args, **_kwargs):
            raise AssertionError(
                f"{name} was raised with nothing to answer it. If the dialog is "
                "the behaviour under test, monkeypatch it in the test."
            )
        return staticmethod(blocked)

    for name in ("question", "warning", "information", "critical", "about"):
        setattr(QMessageBox, name, refuse(f"QMessageBox.{name}"))
    for name in ("getText", "getInt", "getDouble", "getItem", "getMultiLineText"):
        setattr(QInputDialog, name, refuse(f"QInputDialog.{name}"))


@pytest.fixture(autouse=True)
def _no_dialog_nobody_can_answer(monkeypatch):
    refuse_the_dialogs_nobody_can_answer(monkeypatch.setattr)


@pytest.fixture(autouse=True)
def _enhance_presets_of_the_tests_own(monkeypatch, _this_tests_own_folder):
    monkeypatch.setattr(enhance_presets, "PRESETS_PATH",
                        _this_tests_own_folder / "enhance_presets.json")


def pytest_collection_finish(session):
    """gc.freeze moves the import graph out of the full gc.collect() each test's reap runs; collection finish is before pytest-qt's QApplication exists, so no widget is frozen alive. CPython still promotes a cycle made after the freeze through the generations and reaps it in a full collect."""
    gc.collect()
    gc.freeze()


_WIDGET_TAIL_ALLOWANCE_TWICE_THE_26_TO_27_MEASURED = 50


class _DeferredDeleteCounter(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.seen = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.seen += 1
        return False


def _deliver_deferred_deletes() -> int:
    counter = _DeferredDeleteCounter()
    app = QApplication.instance()
    app.installEventFilter(counter)
    try:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        app.removeEventFilter(counter)
    return counter.seen


def _deliver_the_deletions_already_scheduled():
    """A posted deleteLater is delivered only while an event loop spins, and PyQt queues a further deleteLater for each slot object of a destroyed sender, so deliver rounds until one deletes nothing."""
    if QApplication.instance() is None:
        return
    QCoreApplication.sendPostedEvents()
    while _deliver_deferred_deletes():
        QCoreApplication.sendPostedEvents()


def _widgets_something_still_holds() -> int:
    _deliver_the_deletions_already_scheduled()
    gc.collect()
    return len(QApplication.allWidgets())


@pytest.fixture(autouse=True, scope="session")
def _the_live_widget_count_stays_flat():
    before = len(QApplication.allWidgets()) if QApplication.instance() else 0
    yield
    if QApplication.instance() is None:
        return
    grown = _widgets_something_still_holds() - before
    assert grown <= _WIDGET_TAIL_ALLOWANCE_TWICE_THE_26_TO_27_MEASURED, (
        f"{grown} more live widgets at session end than at start: the "
        f"per-test reap is no longer keeping the live object count flat"
    )


@pytest.fixture(scope="session")
def _widgets_registered_this_test():
    """pytest-qt holds registered widgets weakly and spins the event loop once more after the test body, so a collection landing inside a shown gallery's paint frees the tree under it."""
    held = []
    register = QtBot.addWidget

    def register_and_hold(bot, widget, **kwargs):
        register(bot, widget, **kwargs)
        held.append(widget)

    QtBot.addWidget = register_and_hold
    yield held
    QtBot.addWidget = register


@pytest.fixture(autouse=True)
def _collect_widgets_between_tests(_widgets_registered_this_test):
    """Widgets form reference cycles whose C++ objects linger until the cyclic collector runs; collect after each test, then deliver the deletions, and drain again at each test's start because pytest releases the last test's fixtures after every teardown hook."""
    _deliver_the_deletions_already_scheduled()
    yield
    # By now pytest-qt has closed what the test registered, so letting go of it here cannot free anything Qt is still drawing.
    _widgets_registered_this_test.clear()
    gc.collect()
    _deliver_the_deletions_already_scheduled()


@pytest.hookimpl(hookwrapper=True)
def pytest_timeout_cancel_timer(item):
    """pytest-timeout leaves each test's cancel timer on the test once it has run, and every later collection walks them."""
    yield
    vars(item).pop("cancel_timeout", None)


def _print_qt_message(_kind, _context, message):
    print(message, file=sys.stderr)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_thread_hop: leave the gallery's off-thread work on its pool thread")
    qInstallMessageHandler(_print_qt_message)


@pytest.fixture
def _stub_preview_resolution(monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview", lambda row, places: None)


@pytest.fixture(autouse=True)
def _off_thread_work_runs_inline(request, monkeypatch):
    if request.node.get_closest_marker("real_thread_hop"):
        return

    monkeypatch.setattr(GalleryView, "off_thread",
                        lambda self, work, done: done(work()))
    monkeypatch.setattr(CombineController, "_after_painting",
                        lambda self, work: work())


@pytest.fixture(autouse=True)
def _previews_start_running():
    omnipause.freeze(False)
    yield
    omnipause.freeze(False)


@pytest.fixture(autouse=True)
def _no_mouse_button_left_held():
    """QTest carries pressed buttons from one event to the next, so a drag whose QDrag.exec is stood in for leaves its button held for the next test."""
    yield
    if QApplication.instance() is None:
        return
    stand_in = QWidget()
    for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton,
                   Qt.MouseButton.RightButton):
        QTest.mouseRelease(stand_in, button)


@pytest.fixture(autouse=True, scope="session")
def _context_menus_open_on_release(qapp):
    """Offscreen, Qt opens a context menu on the press; Windows opens it on the release."""
    qapp.styleHints().setContextMenuTrigger(Qt.ContextMenuTrigger.Release)


@pytest.fixture(autouse=True)
def _no_outline_detector_but_the_ones_a_test_installs(monkeypatch):
    monkeypatch.setattr(detail_parts, "list_outline_detector_files", list)


@pytest.fixture
def another_program():
    program = subprocess.Popen([sys._base_executable, "-c", "import time; time.sleep(120)"],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    yield program
    program.kill()
    program.wait()
