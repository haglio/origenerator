"""Recorder — push-to-talk microphone capture (sounddevice, injected for tests)."""

import numpy as np

from origenerator.voice.recorder import Recorder


class FakeStream:
    def __init__(self, **kw):
        self.callback = kw["callback"]
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeSoundDevice:
    def __init__(self):
        self.stream = None

    def InputStream(self, **kw):
        self.stream = FakeStream(**kw)
        return self.stream


def _feed(sd, chunk):
    sd.stream.callback(chunk, len(chunk), None, None)


def test_records_and_concatenates_captured_chunks_to_mono():
    sd = FakeSoundDevice()
    recorder = Recorder(sd=sd)
    recorder.start()
    _feed(sd, np.zeros((100, 1), dtype=np.float32))
    _feed(sd, np.ones((50, 1), dtype=np.float32))

    audio = recorder.stop()

    assert audio.shape == (150,)          # one flat mono track
    assert audio[:100].sum() == 0 and audio[100:].sum() == 50
    assert sd.stream.closed                # the stream is released


def test_stop_without_start_returns_none():
    assert Recorder(sd=FakeSoundDevice()).stop() is None


def test_a_silent_capture_returns_none():
    sd = FakeSoundDevice()
    recorder = Recorder(sd=sd)
    recorder.start()
    assert recorder.stop() is None         # nothing captured -> nothing to transcribe
