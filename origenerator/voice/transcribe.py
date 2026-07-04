"""Local speech-to-text with faster-whisper on the CPU.

CPU-only by design: the one GPU is ComfyUI's, and short commands transcribe in
about a second on the ``base`` model. The model is loaded lazily (and is
injectable) so importing this module — and the test suite — never pulls in
faster-whisper or downloads weights. Captured audio is peak-normalized first:
a quiet mic (RMS ~0.03) otherwise transcribes as empty.
"""

import numpy as np

from origenerator.config import WHISPER_MODEL


class Transcriber:
    def __init__(self, *, model_size: str = WHISPER_MODEL, model=None):
        self._model_size = model_size
        self._model = model  # injected in tests; lazily loaded in the app

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    def preload(self) -> None:
        """Load the model now, off the first utterance's critical path."""
        self._load()

    def transcribe(self, audio) -> str:
        """The spoken text in ``audio`` (a mono float32 array), as one line."""
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1e-4:
            audio = audio / peak * 0.95  # boost a faint mic so whisper can read it
        segments, _info = self._load().transcribe(audio, language="en")
        # Whisper segments carry their own leading/trailing spaces; normalise to a
        # single space between non-empty pieces.
        parts = (segment.text.strip() for segment in segments)
        return " ".join(part for part in parts if part)
