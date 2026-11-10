from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread

from origenerator import speech
from origenerator.config import COMFYUI_INPUT_DIR, SPEECH_PYTHON

logger = logging.getLogger(__name__)


def _lines_on_disk(params: dict) -> None:
    speech.ensure_speech_files(params, input_dir=COMFYUI_INPUT_DIR, python=SPEECH_PYTHON)


def _speak(client, params: dict, lines_on_disk) -> None:
    try:
        client.free_memory()
    except Exception as e:  # noqa: BLE001
        logger.info("ComfyUI kept its models while the lines were spoken: %s", e)
    lines_on_disk(params)


class _Speaking(QThread):
    def __init__(self, client, params, lines_on_disk, parent):
        super().__init__(parent)
        self._client = client
        self._params = params
        self._lines_on_disk = lines_on_disk
        self.error: str | None = None

    def run(self):
        try:
            _speak(self._client, self._params, self._lines_on_disk)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)


class Speaker(QObject):
    def __init__(self, client, parent=None, *, lines_on_disk=_lines_on_disk):
        super().__init__(parent)
        self._client = client
        self._lines_on_disk = lines_on_disk

    def speak(self, params: dict, done, failed) -> None:
        # PyQt lets Python collect a QThread with no Qt parent once nothing names it, even while it runs.
        thread = _Speaking(self._client, params, self._lines_on_disk, self)
        thread.finished.connect(lambda: _answer(thread, done, failed))
        thread.start()

    def speak_here(self, params: dict) -> None:
        _speak(self._client, params, self._lines_on_disk)


def _answer(thread, done, failed) -> None:
    thread.deleteLater()
    if thread.error is None:
        done()
    else:
        failed(thread.error)
