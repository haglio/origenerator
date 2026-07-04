"""Continuous microphone listening for voice-steered auto-generate.

While a folder is auto-generating, the mic is open the whole time (the user chose
hands-free over push-to-talk). :class:`UtteranceSegmenter` turns the frame stream
into discrete utterances; :class:`Listener` wires it to a ``sounddevice`` input
stream (lazily imported) and emits each finished utterance for transcription.

Detection is adaptive: the first frames calibrate the mic's ambient level and the
speech threshold tracks it (``noise * ratio``), so a faint or noisy mic — where a
fixed gate sits on top of the background and never endpoints — still works.
"""

import logging

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what faster-whisper expects

_FRAME_MS = 30  # a mic block; ~30 ms is the usual granularity for speech endpointing
_FRAME_SAMPLES = SAMPLE_RATE * _FRAME_MS // 1000


class UtteranceSegmenter:
    """Emits a finished utterance once speech (energy above the calibrated noise
    floor) is followed by ``hangover_frames`` quiet ones, discarding runs shorter
    than ``min_speech_frames``. The first ``calibration_frames`` measure ambient so
    the threshold (``noise * ratio``, never below ``floor``) fits the mic. Pure and
    frame-driven — no audio backend."""

    def __init__(self, *, floor=0.008, ratio=2.0, calibration_frames=15,
                 hangover_frames=20, min_speech_frames=5):
        self._floor = floor
        self._ratio = ratio
        self._calibration_frames = calibration_frames
        self._hangover = hangover_frames
        self._min_speech = min_speech_frames
        self._noise = None  # set once calibration finishes
        self._calib_sum = 0.0
        self._calib_count = 0
        self._buf: list = []
        self._speech_frames = 0
        self._silence_run = 0
        self._in_speech = False

    @property
    def threshold(self) -> float:
        base = self._noise if self._noise is not None else self._floor
        return max(self._floor, base * self._ratio)

    def push(self, frame):
        """Feed one audio frame. Returns the completed utterance (a mono array) when
        speech has just ended, otherwise ``None``."""
        rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
        if self._noise is None:  # still calibrating the ambient level
            self._calib_sum += rms
            self._calib_count += 1
            if self._calib_count >= self._calibration_frames:
                self._noise = self._calib_sum / self._calib_count
            return None
        if rms >= self.threshold:
            self._in_speech = True
            self._silence_run = 0
            self._speech_frames += 1
            self._buf.append(frame)
            return None
        self._noise = 0.98 * self._noise + 0.02 * rms  # track ambient drift on quiet
        if not self._in_speech:
            return None
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

    def __init__(self, *, floor=0.008, sd=None, parent=None):
        super().__init__(parent)
        self._floor = floor
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
        self._segmenter = UtteranceSegmenter(floor=self._floor)
        self._stream = self._backend().InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=_FRAME_SAMPLES, callback=self._on_audio,
        )
        self._stream.start()
        self._frame_count = 0
        self._peak_rms = 0.0
        logger.info("Voice: mic opened (calibrating ambient, floor=%.3f)", self._floor)

    def _on_audio(self, indata, _frames, _time, _status):
        frame = np.asarray(indata).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
        self._peak_rms = max(self._peak_rms, rms)
        self._frame_count += 1
        if self._frame_count % 100 == 0:  # ~every 3s: is the mic hearing speech?
            if self._peak_rms > 0.005:
                logger.info("Voice: mic peak RMS %.4f vs adaptive threshold %.4f",
                            self._peak_rms, self._segmenter.threshold)
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
