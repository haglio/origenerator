"""Capture microphone audio for push-to-talk voice commands.

Records mono float32 at 16 kHz — what faster-whisper expects — while the mic
button is held. ``sounddevice`` is imported lazily (and injectable) so importing
this module, and the whole test suite, never needs the audio backend installed.
"""

import numpy as np

SAMPLE_RATE = 16000  # faster-whisper's native rate


class Recorder:
    def __init__(self, *, sample_rate: int = SAMPLE_RATE, sd=None):
        self._sample_rate = sample_rate
        self._sd = sd  # injected in tests; lazily imported in the app
        self._stream = None
        self._chunks: list = []

    def _backend(self):
        if self._sd is None:
            import sounddevice
            self._sd = sounddevice
        return self._sd

    def start(self) -> None:
        """Open the mic stream and begin buffering audio."""
        self._chunks = []
        self._stream = self._backend().InputStream(
            samplerate=self._sample_rate, channels=1, dtype="float32",
            callback=self._on_audio,
        )
        self._stream.start()

    def _on_audio(self, indata, _frames, _time, _status) -> None:
        self._chunks.append(np.asarray(indata).copy())

    def stop(self):
        """Close the stream and return the captured mono track, or ``None`` when
        nothing was recorded (never started, or a silent/empty capture)."""
        if self._stream is None:
            return None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._chunks:
            return None
        return np.concatenate(self._chunks, axis=0).reshape(-1)
