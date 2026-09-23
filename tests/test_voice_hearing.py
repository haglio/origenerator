"""The microphone as text: what reaches the app, and as what words.

Hearing itself is voice_core's and tested there; these hold what is this app's own --
which of its two roads an utterance takes, and what arrives at the end of each.
"""
from __future__ import annotations

import array
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from voice_core.listener import Engines
from voice_core.whisper_reader import WhisperReader

from origenerator.voice.dictation import request_bias
from origenerator.voice.hearing import Hearing

QUIET = bytes(960)  # one 30 ms frame of digital silence
LOUD = array.array("h", [3000, -3000] * 240).tobytes()
ONE_UTTERANCE = [QUIET] * 15 + [LOUD] * 8 + [QUIET] * 20
PATIENCE_MS = 10_000


class _Recognizer:
    def __init__(self, readings):
        self._readings = readings

    def SetWords(self, enable):  # noqa: N802 - vosk's own name
        pass

    def SetMaxAlternatives(self, count):  # noqa: N802 - vosk's own name
        pass

    def AcceptWaveform(self, _frame):  # noqa: N802 - vosk's own name
        return False

    def Reset(self):  # noqa: N802 - vosk's own name
        pass

    def PartialResult(self):  # noqa: N802 - vosk's own name
        return json.dumps({"partial": ""})

    def FinalResult(self):  # noqa: N802 - vosk's own name
        return json.dumps({"alternatives": [
            {"text": reading, "confidence": 1.0} for reading in self._readings]})


def _engines(readings, *, frames=None, **more):
    """Fake vosk and sounddevice: a microphone that delivers one utterance (or *frames*),
    which the recognizer reads as *readings*, best first."""
    devices = [{"name": "Desk mic", "max_input_channels": 1, "hostapi": 0}]

    @contextmanager
    def stream(**kwargs):
        for frame in frames or ONE_UTTERANCE:
            kwargs["callback"](frame, len(frame) // 2, None, None)
        yield

    return Engines(
        vosk=SimpleNamespace(Model=lambda model_name: model_name,
                             KaldiRecognizer=lambda *args: _Recognizer(readings)),
        sounddevice=SimpleNamespace(
            default=SimpleNamespace(device=(0, 0)),
            query_devices=lambda index=None: devices if index is None else devices[index],
            RawInputStream=stream),
        **more)


def _said(qtbot, hearing):
    with qtbot.waitSignal(hearing.said, timeout=PATIENCE_MS) as said:
        hearing.start()
    hearing.stop()
    return said.args[0]


def test_a_command_said_outright_arrives_as_its_own_words(qtbot):
    hearing = Hearing({"undo", "star it"}, engines=_engines(["star it"]))

    assert _said(qtbot, hearing) == "star it"


def test_a_sentence_arrives_as_the_words_it_was_taken_down_as(qtbot):
    hearing = Hearing({"undo"}, engines=_engines(
        ["[unk]"], take_down=lambda audio, hint: "make her hair longer"))

    assert _said(qtbot, hearing) == "make her hair longer"


def test_a_phrase_the_second_listener_reads_differently_arrives_as_the_sentence_it_was(qtbot):
    # Said mid-thought, "undo the last one" is not the command its first word is.
    hearing = Hearing({"undo"}, engines=_engines(
        ["undo"], second_opinion=lambda audio, hint: "undo the last one",
        take_down=lambda audio, hint: "undo the last one"))

    assert _said(qtbot, hearing) == "undo the last one"


def test_a_quiet_sound_with_no_words_in_it_is_not_worth_a_caption(qtbot):
    # The pause detector hears far quieter sounds than this app's own did, which is what
    # lets a quiet word through; a quiet nothing is a chair, not something to answer.
    faint = array.array("h", [400, -400] * 240).tobytes()
    engines = _engines([""], take_down=lambda audio, hint: " . . . ",
                       frames=[QUIET] * 15 + [faint] * 8 + [QUIET] * 20 + ONE_UTTERANCE[15:])
    hearing = Hearing({"undo"}, engines=engines)
    arrived = []
    hearing.said.connect(arrived.append)

    with qtbot.waitSignal(hearing.said, timeout=PATIENCE_MS):
        hearing.start()
    hearing.stop()

    assert arrived == [" . . . "]  # the loud one alone


def test_a_sound_with_no_words_in_it_arrives_as_nothing_so_the_caption_can_say_so(qtbot):
    hearing = Hearing({"undo"}, engines=_engines([""], take_down=lambda audio, hint: ""))

    assert _said(qtbot, hearing) == ""


def test_a_phrase_that_cannot_be_taken_back_by_voice_is_heard_only_as_the_first_reading(qtbot):
    # "mic off" has no spoken way back, so a near miss is never repaired into it.
    hearing = Hearing({"mic off", "audio off"}, never_repaired={"mic off"}, engines=_engines(
        ["mic audio off", "mic off"], take_down=lambda audio, hint: "my audio is off"))

    assert _said(qtbot, hearing) == "my audio is off"


def test_a_microphone_that_cannot_be_opened_is_reported_with_its_reason(qtbot):
    engines = _engines(["undo"])
    engines.sounddevice.RawInputStream = Mock(side_effect=OSError("no input device"))
    hearing = Hearing({"undo"}, engines=engines)

    with qtbot.waitSignal(hearing.failed, timeout=PATIENCE_MS) as failed:
        hearing.start()
    hearing.stop()

    assert failed.args == ["no input device"]


def test_left_to_itself_it_listens_the_way_this_app_needs(qtbot, monkeypatch):
    built = Mock()
    monkeypatch.setattr("origenerator.voice.hearing.CommandListener", built)
    monkeypatch.setattr("origenerator.config.VOICE_MODEL_NAME", "a-model")
    monkeypatch.setattr("origenerator.config.VOICE_DEVICE_NAME", "a-microphone")

    hearing = Hearing({"undo"})
    hearing.start()
    hearing.stop()

    _rules, settings, _events, engines = built.call_args.args
    # A sentence ends where the speaker pauses, and what is taken down is told to expect
    # the two words a spoken request hangs on.
    assert (settings.model_name, settings.device_name) == ("a-model", "a-microphone")
    assert settings.pauses is not None
    assert settings.speech_hint == request_bias()
    # Nothing said here reaches the disk.
    assert settings.miss_dir is None
    assert isinstance(engines.second_opinion, WhisperReader)
    assert isinstance(engines.take_down, WhisperReader)
    assert engines.take_down is not engines.second_opinion
