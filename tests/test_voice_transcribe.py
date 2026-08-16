"""Transcriber — local speech-to-text over faster-whisper (model injected)."""

import sys
import types

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


def test_the_prompt_bias_rides_along_as_whispers_initial_prompt():
    # Off a quiet mic whisper mangles a short imperative ("fix <part>" came
    # back as other words entirely); the caller's vocabulary bias is what
    # steers the decode, so it must actually reach the model.
    model = FakeModel([_Segment("fix teeth")])
    Transcriber(model=model, prompt_bias="Voice commands: fix.").transcribe(
        np.array([0.2, -0.2], dtype=np.float32))
    assert model.calls[0][1]["initial_prompt"] == "Voice commands: fix."


def test_no_bias_means_none_reaches_the_model():
    model = FakeModel([_Segment("go")])
    Transcriber(model=model).transcribe(np.array([0.2], dtype=np.float32))
    assert model.calls[0][1]["initial_prompt"] is None


def test_loading_refuses_the_optional_torch_import(monkeypatch):
    # faster-whisper needs no torch but imports any it finds — and a torch
    # that loads fine on its own can die initializing its DLLs once Qt is in
    # the process (WinError 1114), taking every transcription with it. The
    # lazy load blocks the optional import before touching faster_whisper.
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = lambda *args, **kwargs: FakeModel([])
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.delitem(sys.modules, "torch", raising=False)

    Transcriber().preload()

    assert sys.modules.get("torch", "absent") is None
    monkeypatch.delitem(sys.modules, "torch", raising=False)


def test_a_torch_already_imported_is_left_alone(monkeypatch):
    # The block is for the import faster-whisper would trigger, not a purge:
    # anything that already imported a working torch keeps it.
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = lambda *args, **kwargs: FakeModel([])
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    already = types.ModuleType("torch")
    monkeypatch.setitem(sys.modules, "torch", already)

    Transcriber().preload()

    assert sys.modules["torch"] is already
