"""Origenerator opened and closed for real, in a process of its own.

Run as ``python -m tests.real_close <file>`` by test_app's test of the close,
with the state folder it is to use in ``ORIGENERATOR_STATE_DIR``. It writes to
*file*, as JSON, how many of each kind of QObject Python still owned as the
QApplication's own wrapper was freed: the moment PyQt deletes each of them itself.
"""
from __future__ import annotations

import collections
import gc
import json
import socket
import sys
import weakref
from pathlib import Path

import tests.conftest as suite
from tests.children import say_where_it_hangs

# isort: split
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QObject, QTimer
from PyQt6.QtWidgets import QApplication

from origenerator import app, config

CLOSED_AFTER_MS = 200

_the_application = None


def _a_port_nothing_answers_on() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _owned_by_python() -> dict[str, int]:
    kinds = collections.Counter()
    for found in gc.get_objects():
        try:
            if not isinstance(found, QObject) or isinstance(found, QCoreApplication):
                continue
        except ReferenceError:
            continue
        if not sip.isdeleted(found) and sip.ispyowned(found):
            kinds[type(found).__name__] += 1
    return dict(sorted(kinds.items()))


def _say_what_python_owns(_freed) -> None:
    Path(sys.argv[1]).write_text(json.dumps(_owned_by_python()), encoding="utf-8")


def _built_then_closed(build):
    def build_then_close(*args, **kwargs):
        global _the_application
        window = build(*args, **kwargs)
        _the_application = weakref.ref(QApplication.instance(), _say_what_python_owns)
        QTimer.singleShot(CLOSED_AFTER_MS, window.close)
        return window
    return build_then_close


def main() -> int:
    say_where_it_hangs()
    for keep_off in (suite.keep_the_microphone_shut, suite.refuse_the_comfyui_on_this_machine,
                     suite.keep_off_the_device, suite.keep_out_of_windows, suite.keep_silent,
                     suite.refuse_the_dialogs_nobody_can_answer):
        keep_off(setattr)
    config.COMFYUI_PORT = _a_port_nothing_answers_on()
    app._build_window = _built_then_closed(app._build_window)
    return app.main([])


raise SystemExit(main())
