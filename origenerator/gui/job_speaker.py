from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread

from origenerator import speech
from origenerator.config import COMFYUI_INPUT_DIR, SPEECH_PYTHON

logger = logging.getLogger(__name__)


def _speak(client, params: dict) -> None:
    try:
        client.free_memory()
    except Exception as e:  # noqa: BLE001
        logger.info("ComfyUI kept its models while the lines were spoken: %s", e)
    speech.ensure_speech_files(params, input_dir=COMFYUI_INPUT_DIR, python=SPEECH_PYTHON)


class _Speaking(QThread):
    def __init__(self, client, params, parent):
        super().__init__(parent)
        self._client = client
        self._params = params
        self.error: str | None = None

    def run(self):
        try:
            _speak(self._client, self._params)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)


class Speaker(QObject):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self._client = client

    def speak(self, params: dict, done, failed) -> None:
        thread = _Speaking(self._client, params, self)
        thread.finished.connect(lambda: _answer(thread, done, failed))
        thread.start()

    def speak_here(self, params: dict) -> None:
        _speak(self._client, params)


def _answer(thread, done, failed) -> None:
    thread.deleteLater()
    if thread.error is None:
        done()
    else:
        failed(thread.error)
