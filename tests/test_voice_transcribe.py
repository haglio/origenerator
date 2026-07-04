"""Transcriber — local speech-to-text over faster-whisper (model injected)."""

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
    model = FakeModel([_Segment(" no "), _Segment("redacted")])
    transcriber = Transcriber(model=model)
    assert transcriber.transcribe(object()) == "no redacted"


def test_passes_the_audio_through_to_the_model():
    model = FakeModel([_Segment("go")])
    audio = object()
    Transcriber(model=model).transcribe(audio)
    assert model.calls[0][0] is audio
