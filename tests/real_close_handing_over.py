"""Origenerator opened and closed for real with its queue still holding work.

Run as ``python -m tests.real_close_handing_over <file>`` by test_app, with the
state folder it is to use in ``ORIGENERATOR_STATE_DIR``. The library holds three
images the queue was holding when the app last closed: the window takes them
back into its line and hands ComfyUI the first, so two are still waiting when it
is closed, and ComfyUI is a stand-in that takes a moment over each. It writes to
*file*, as JSON, when the window was asked to close, when the app's last window
closed and when each hand-over began, on one clock.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from tests.real_close import open_and_close

# isort: split
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication

from origenerator import config
from origenerator.comfyui_api import ComfyUIApi
from origenerator.db import Database
from origenerator.workflows import WORKFLOW_REGISTRY

A_MOMENT_S = 0.3

_when = {"asked_to_close": [], "went": [], "asked": []}


def _images_waiting_in_the_line() -> None:
    workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    db = Database(config.DB_PATH)
    for seed in (1, 2, 3):
        prompt_id = f"waiting-{seed}"
        db.insert_generation(prompt_id=prompt_id, workflow_name=workflow.name,
                             workflow_version=workflow.version, positive_prompt="a cat",
                             seed=seed, workflow_json="{}",
                             params_json=json.dumps(dict(workflow.default_params(),
                                                         positive_prompt="a cat", seed=seed)))
        db.update_generation(prompt_id, status="pending")


def _take_a_moment_over_it(_api, _payload, prompt_id):
    _when["asked"].append(time.monotonic())
    time.sleep(A_MOMENT_S)
    return prompt_id


class _CloseAsked(QObject):
    def eventFilter(self, _watched, event):  # noqa: N802 -- Qt's name
        if event.type() == QEvent.Type.Close:
            _when["asked_to_close"].append(time.monotonic())
        return False


_close_asked = _CloseAsked()


def _note_when_the_window_goes(window) -> None:
    window.installEventFilter(_close_asked)
    QApplication.instance().lastWindowClosed.connect(
        lambda: _when["went"].append(time.monotonic()))


def main() -> int:
    _images_waiting_in_the_line()
    ComfyUIApi.submit_job = _take_a_moment_over_it
    ended = open_and_close(_note_when_the_window_goes)
    Path(sys.argv[1]).write_text(json.dumps(_when), encoding="utf-8")
    return ended


if __name__ == "__main__":
    raise SystemExit(main())
