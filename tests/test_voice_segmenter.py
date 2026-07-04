"""UtteranceSegmenter — energy-based endpointing of a live mic stream.

Buffers frames once they're loud enough and emits a finished utterance when the
speech is followed by enough quiet frames, discarding blips too short to be a
command. Pure and frame-driven, so it tests without a microphone.
"""

import numpy as np

from origenerator.voice.listener import UtteranceSegmenter

SILENCE = np.zeros(4, dtype=np.float32)
SPEECH = np.full(4, 0.5, dtype=np.float32)


def _seg(**kw):
    kw.setdefault("threshold", 0.1)
    kw.setdefault("hangover_frames", 3)
    kw.setdefault("min_speech_frames", 2)
    return UtteranceSegmenter(**kw)


def test_silence_never_produces_an_utterance():
    seg = _seg()
    assert all(seg.push(SILENCE) is None for _ in range(10))


def test_speech_then_a_quiet_gap_yields_the_utterance():
    seg = _seg()
    assert seg.push(SPEECH) is None    # speech 1
    assert seg.push(SPEECH) is None    # speech 2 (meets the minimum)
    assert seg.push(SILENCE) is None   # quiet 1
    assert seg.push(SILENCE) is None   # quiet 2
    utterance = seg.push(SILENCE)      # quiet 3 -> endpointed

    assert utterance is not None
    assert len(utterance) >= 8         # at least the two speech frames' samples


def test_a_blip_shorter_than_min_speech_is_discarded():
    seg = _seg()
    seg.push(SPEECH)                   # a lone speech frame, below the minimum
    result = None
    for _ in range(3):
        result = seg.push(SILENCE)
    assert result is None              # endpointed, but discarded as too short


def test_detects_two_successive_utterances():
    seg = _seg()
    first = [seg.push(f) for f in (SPEECH, SPEECH, SILENCE, SILENCE, SILENCE)]
    second = [seg.push(f) for f in (SPEECH, SPEECH, SILENCE, SILENCE, SILENCE)]
    assert any(u is not None for u in first)
    assert any(u is not None for u in second)
