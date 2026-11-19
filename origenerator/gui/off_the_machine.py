from __future__ import annotations

import errno
import socket
import urllib.error
import urllib.parse
import urllib.request
import winsound

from app_support import win32 as windows_api
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QInputDialog, QMessageBox

from origenerator import (
    config,
    osr2_driver,
    osr2_motion_driver,
    toast_raising,
)
from origenerator.gui import job_queue, link_listener, osr2_controls, toasts
from origenerator.voice import listener


def refuse_the_comfyui_on_this_machine(setattr) -> None:
    real_urlopen = urllib.request.urlopen
    llm = urllib.parse.urlsplit(config.LOCAL_LLM_BASE_URL)
    refused = {(config.COMFYUI_HOST, config.COMFYUI_PORT), (llm.hostname, llm.port)}

    def urlopen(url, *args, **kwargs):
        target = urllib.parse.urlsplit(getattr(url, "full_url", url))
        if (target.hostname, target.port) in refused:
            raise urllib.error.URLError(ConnectionRefusedError(
                errno.ECONNREFUSED, "nothing kept off this machine reaches a service on it"))
        return real_urlopen(url, *args, **kwargs)

    setattr(urllib.request, "urlopen", urlopen)


def a_port_nothing_answers_on() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def talk_to_no_comfyui_on_this_machine(setattr) -> None:
    setattr(config, "COMFYUI_PORT", a_port_nothing_answers_on())


def start_no_comfyui_on_this_machine(setattr) -> None:
    setattr(job_queue, "BRING_UP_COMFYUI", None)


def keep_off_the_device(setattr) -> None:
    class _NoDevice:
        def want(self, wanted): pass
        def ask(self, verb): pass
        def send_position(self, pos, interval_ms): pass
        def close(self): pass

    setattr(osr2_driver, "Osr2Broker", lambda *a, **k: _NoDevice())
    setattr(osr2_motion_driver, "Osr2Broker", lambda *a, **k: _NoDevice())
    the_device_is_there = osr2_controls.osr2.osr2_device.Osr2Mode.CONTROLLED
    setattr(osr2_controls.osr2, "device_mode", lambda **_kw: the_device_is_there)
    setattr(osr2_controls.osr2, "device_trouble", lambda **_kw: None)
    setattr(osr2_controls.osr2, "broker_running", lambda **_kw: True)
    setattr(osr2_controls.osr2, "press_the_broker", lambda **_kw: None)


def keep_out_of_windows(setattr) -> None:
    setattr(windows_api, "dress_window", lambda *_a, **_kw: None)
    setattr(toasts, "register_toast_identity", lambda *_a, **_kw: None)
    setattr(toasts, "register_link_handler", lambda *_a, **_kw: None)
    setattr(toast_raising, "show", lambda *_a, **_kw: None)
    setattr(toast_raising, "take_back", lambda *_a, **_kw: None)


class _AnswersNoToastClicks(QObject):
    def __init__(self, *, checkout, environ=None, parent=None):
        super().__init__(parent)

    def answer_with(self, go_to) -> None:
        pass


def answer_no_toast_clicks(setattr) -> None:
    setattr(link_listener, "LinkListener", _AnswersNoToastClicks)


class DeafHearing(QObject):
    said = Signal(str, float)
    failed = Signal(str)

    def __init__(self, *_args, **_kwargs):
        super().__init__()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def keep_the_microphone_deaf(setattr) -> None:
    setattr(listener, "Hearing", DeafHearing)


def keep_silent(setattr) -> list:
    sounded = []
    setattr(winsound, "MessageBeep", sounded.append)
    return sounded


def refuse_the_dialogs_nobody_can_answer(setattr) -> None:
    """A Qt offscreen modal dialog spins a nested event loop nobody can end, so the run would hang instead of failing."""
    def refuse(name):
        def blocked(*_args, **_kwargs):
            raise AssertionError(
                f"{name} was raised with nothing to answer it. If the dialog is "
                "the behavior under test, monkeypatch it in the test."
            )
        return staticmethod(blocked)

    for name in ("question", "warning", "information", "critical", "about"):
        setattr(QMessageBox, name, refuse(f"QMessageBox.{name}"))
    for name in ("getText", "getInt", "getDouble", "getItem", "getMultiLineText"):
        setattr(QInputDialog, name, refuse(f"QInputDialog.{name}"))


EVERYTHING_OFF_THE_MACHINE = (
    refuse_the_comfyui_on_this_machine, talk_to_no_comfyui_on_this_machine,
    start_no_comfyui_on_this_machine, keep_off_the_device,
    keep_out_of_windows, answer_no_toast_clicks, keep_the_microphone_deaf, keep_silent,
    refuse_the_dialogs_nobody_can_answer,
)
