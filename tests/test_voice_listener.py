"""Listener — the captured utterance must survive sounddevice reusing its buffer."""

import numpy as np

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
