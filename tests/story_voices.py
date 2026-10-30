"""A story's voice, faked: which way each was asked to speak, and the answer it owes."""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator.gui import generation_job


class AskedVoice(NamedTuple):
    how: str  # "later", off the window's thread, or "here", where it was asked
    lines: list[str]
    done: Callable[[], None] | None  # what a voice asked for later calls once it has spoken


def voices_asked_for(monkeypatch) -> list[AskedVoice]:
    """A story's lines unspoken until a voice speaks them, and each voice asked for, recorded."""
    asked: list[AskedVoice] = []

    class _Voice:
        def __init__(self, client):
            pass

        def speak(self, params, done, failed):
            asked.append(AskedVoice("later", params["scene_lines"], done))

        def speak_here(self, params):
            asked.append(AskedVoice("here", params["scene_lines"], None))

    monkeypatch.setattr(generation_job, "Speaker", _Voice)
    monkeypatch.setattr(generation_job.speech, "missing_speech", lambda params, input_dir: [
        line for line in params.get("scene_lines") or [] if line.strip()])
    return asked
