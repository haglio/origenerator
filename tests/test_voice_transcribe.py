"""Transcriber — local speech-to-text over faster-whisper (model injected)."""

import numpy as np

from origenerator.voice.transcribe import Transcriber


class _Segment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return (iter(self._segments), object())


def test_joins_segment_text_into_one_instruction():
    model = FakeModel([_Segment(" no "), _Segment("hat")])
    transcriber = Transcriber(model=model)
    assert transcriber.transcribe(np.array([0.2, -0.2], dtype=np.float32)) == "no hat"


def test_peak_normalizes_faint_audio_before_transcribing():
    model = FakeModel([_Segment("go")])
    Transcriber(model=model).transcribe(np.array([0.01, -0.02, 0.015], dtype=np.float32))
    sent = model.calls[0][0]
    assert abs(float(np.max(np.abs(sent))) - 0.95) < 1e-3  # boosted to a usable level
