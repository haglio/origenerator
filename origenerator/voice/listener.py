"""Continuous microphone listening for voice-steered auto-generate.

While a folder is auto-generating, the mic is open the whole time (the user chose
hands-free over push-to-talk). :class:`UtteranceSegmenter` is a pure energy-based
endpointer that turns the frame stream into discrete utterances; :class:`Listener`
wires it to a ``sounddevice`` input stream (lazily imported) and emits each
finished utterance for transcription. Energy-based detection is deliberately
simple and will occasionally trip on background/TV speech — the accepted cost of
hands-free — so ``threshold`` is tunable.
"""

import logging

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what faster-whisper expects

_FRAME_MS = 30  # a mic block; ~30 ms is the usual granularity for speech endpointing
_FRAME_SAMPLES = SAMPLE_RATE * _FRAME_MS // 1000


class UtteranceSegmenter:
    """Emits a finished utterance once loud frames are followed by ``hangover_frames``
    quiet ones, discarding runs shorter than ``min_speech_frames``. Pure and
    frame-driven — energy/VAD detection is all it does, no audio backend."""

    def __init__(self, *, threshold=0.02, hangover_frames=25, min_speech_frames=8):
        self._threshold = threshold
        self._hangover = hangover_frames
        self._min_speech = min_speech_frames
        self._buf: list = []
        self._speech_frames = 0
        self._silence_run = 0
        self._in_speech = False

    def push(self, frame):
        """Feed one audio frame. Returns the completed utterance (a mono array) when
        speech has just ended, otherwise ``None``."""
        rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
        if rms >= self._threshold:
            self._in_speech = True
            self._silence_run = 0
            self._speech_frames += 1
            self._buf.append(frame)
            return None
        if not self._in_speech:
            return None  # still waiting for speech to begin
        self._silence_run += 1
        self._buf.append(frame)  # keep the trailing quiet; whisper reads it better
        if self._silence_run >= self._hangover:
            return self._finish()
        return None

    def _finish(self):
        frames, speech = self._buf, self._speech_frames
        self._buf, self._speech_frames, self._silence_run, self._in_speech = [], 0, 0, False
        if speech < self._min_speech:
            return None  # a cough/click, not a command
        return np.concatenate(frames)


class Listener(QObject):
    """Opens the mic and emits each endpointed utterance. ``sounddevice`` is
    injectable and otherwise imported lazily, so nothing here needs the audio
    backend until :meth:`start` actually runs."""

    utterance = pyqtSignal(object)  # a finished utterance (mono float32 array)

    def __init__(self, *, threshold=0.02, sd=None, parent=None):
        super().__init__(parent)
        self._threshold = threshold
        self._sd = sd
        self._stream = None
        self._segmenter = None
        self._frame_count = 0
        self._peak_rms = 0.0

    def _backend(self):
        if self._sd is None:
            import sounddevice
            self._sd = sounddevice
        return self._sd

    def start(self):
        if self._stream is not None:
            return
        self._segmenter = UtteranceSegmenter(threshold=self._threshold)
        self._stream = self._backend().InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=_FRAME_SAMPLES, callback=self._on_audio,
        )
        self._stream.start()
        self._frame_count = 0
        self._peak_rms = 0.0
        logger.info("Voice: mic opened (VAD threshold=%.3f)", self._threshold)

    def _on_audio(self, indata, _frames, _time, _status):
        frame = np.asarray(indata).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
        self._peak_rms = max(self._peak_rms, rms)
        self._frame_count += 1
        if self._frame_count % 100 == 0:  # ~every 3s: is the mic hearing anything?
            if self._peak_rms > 0.005:
                logger.info("Voice: mic peak RMS %.4f vs threshold %.3f",
                            self._peak_rms, self._threshold)
            self._peak_rms = 0.0
        completed = self._segmenter.push(frame)
        if completed is not None:
            logger.info("Voice: utterance captured (%d samples)", len(completed))
            self.utterance.emit(completed)  # queued to the owner's thread

    def stop(self):
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._segmenter = None
