"""Listener — the captured utterance must survive sounddevice reusing its buffer."""

import numpy as np

from origenerator.voice import listener as listener_module
from origenerator.voice.listener import Listener


class FakeStream:
    def __init__(self, **kw):
        self.callback = kw["callback"]

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class FakeSoundDevice:
    def InputStream(self, **kw):
        self.stream = FakeStream(**kw)
        return self.stream


def test_captured_audio_survives_the_reused_input_buffer(qtbot):
    # sounddevice hands the *same* buffer to each callback and overwrites it in
    # place; if the listener stored a view instead of a copy, the buffered
    # utterance would end up holding the final (silent) contents.
    sd = FakeSoundDevice()
    listener = Listener(floor=0.001, sd=sd)
    captured = []
    listener.utterance.connect(captured.append)
    listener.start()
    callback = sd.stream.callback

    buffer = np.zeros((480, 1), dtype=np.float32)

    def feed(level, count):
        for _ in range(count):
            buffer[:] = level               # sounddevice fills its reused buffer...
            callback(buffer, 480, None, None)  # ...then hands that same object over

    feed(0.0, 15)   # calibrate on quiet
    feed(0.3, 8)    # speech
    feed(0.0, 20)   # quiet -> endpoint (buffer is now silent)

    assert captured, "no utterance emitted"
    assert float(np.sqrt(np.mean(captured[0] ** 2))) > 0.05  # the speech was copied out


def test_a_captured_utterance_is_not_written_to_disk(qtbot, tmp_path, monkeypatch):
    # This package promises the audio never leaves the machine, and a wav of the
    # last thing said, left in the state dir by a probe from a finished bug hunt,
    # is the nearest thing to breaking that promise -- written on the audio
    # callback's own thread, for a reader that does not exist. `raising=False`
    # because the point is that the module needs no state dir at all now.
    monkeypatch.setattr(listener_module, "STATE_DIR", tmp_path, raising=False)
    sd = FakeSoundDevice()
    listener = Listener(floor=0.001, sd=sd)
    captured = []
    listener.utterance.connect(captured.append)
    listener.start()
    buffer = np.zeros((480, 1), dtype=np.float32)
    for level, count in ((0.0, 15), (0.3, 8), (0.0, 20)):
        for _ in range(count):
            buffer[:] = level
            sd.stream.callback(buffer, 480, None, None)

    assert captured, "no utterance emitted"
    assert list(tmp_path.iterdir()) == []
