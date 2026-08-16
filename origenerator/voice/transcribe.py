"""Local speech-to-text with faster-whisper on the CPU.

CPU-only by design: the one GPU is ComfyUI's, and short commands transcribe in
about a second on the ``base`` model. The model is loaded lazily (and is
injectable) so importing this module — and the test suite — never pulls in
faster-whisper or downloads weights. Captured audio is peak-normalized first:
a quiet mic (RMS ~0.03) otherwise transcribes as empty.
"""

import sys

import numpy as np

from origenerator.config import WHISPER_MODEL


class Transcriber:
    def __init__(self, *, model_size: str = WHISPER_MODEL, model=None,
                 prompt_bias: str | None = None):
        self._model_size = model_size
        self._model = model  # injected in tests; lazily loaded in the app
        # Domain vocabulary fed to whisper as its initial prompt. Off a quiet
        # mic the model takes real liberties with short imperatives — a
        # captured "fix <part>" replayed as "thick stick", and hotwords didn't
        # move it, while this exact bias flipped the same audio to the words
        # said — so the caller hands in the phrases it expects to hear.
        self._prompt_bias = prompt_bias

    def _load(self):
        if self._model is None:
            # faster-whisper runs on ctranslate2 and needs no torch — but it
            # imports any torch it finds, and a torch that loads fine on its
            # own can die initializing c10.dll once Qt's DLLs are in the
            # process (WinError 1114 — the same import-after-Qt failure
            # onnxruntime had), taking every transcription with it. Refusing
            # the optional import keeps whisper on its own torch-free path.
            # setdefault: a torch something else already imported stays.
            sys.modules.setdefault("torch", None)
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
        # vad_filter uses the bundled Silero VAD to isolate speech within the clip,
        # which helps whisper find words in a noisy capture.
        segments, _info = self._load().transcribe(
            audio, language="en", vad_filter=True, initial_prompt=self._prompt_bias)
        # Whisper segments carry their own leading/trailing spaces; normalise to a
        # single space between non-empty pieces.
        parts = (segment.text.strip() for segment in segments)
        return " ".join(part for part in parts if part)
