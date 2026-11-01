"""The microphone as text: what reaches the app, and as what words.

Hearing itself is voice_core's and tested there; these hold what is this app's own --
which of its two roads an utterance takes, and what arrives at the end of each.
"""
from __future__ import annotations

import array
from unittest.mock import Mock

import pytest
from voice_core.speech import HearsSpeech
from voice_core.testing import said, scripted_engines
from voice_core.whisper_reader import WhisperReader

from origenerator.voice.dictation import request_bias
from origenerator.voice.hearing import Hearing

QUIET = bytes(960)  # one 30 ms frame of digital silence
LOUD = array.array("h", [3000, -3000] * 240).tobytes()
ONE_UTTERANCE = [QUIET] * 15 + [LOUD] * 8 + [QUIET] * 20
PATIENCE_MS = 10_000


def _engines(readings, **more):
    return scripted_engines([said(*readings)], frames=ONE_UTTERANCE, **more)


def _said(qtbot, hearing):
    with qtbot.waitSignal(hearing.said, timeout=PATIENCE_MS) as arrived:
        hearing.start()
    hearing.stop()
    return arrived.args[0]


def test_a_command_said_outright_arrives_as_its_own_words(qtbot):
    hearing = Hearing({"undo", "star it"}, engines=_engines(["star it"]))

    assert _said(qtbot, hearing) == "star it"


def test_a_word_arrives_with_the_time_it_began_to_be_said(qtbot):
    hearing = Hearing({"undo", "star it"}, engines=_engines(["star it"], clock=lambda: 50.0))

    with qtbot.waitSignal(hearing.said, timeout=PATIENCE_MS) as arrived:
        hearing.start()
    hearing.stop()

    assert arrived.args[1] == pytest.approx(50.0, abs=2.0)


def test_a_sentence_arrives_as_the_words_it_was_taken_down_as(qtbot):
    hearing = Hearing({"undo"}, engines=_engines(
        ["[unk]"], take_down=lambda audio, hint: "make her hair longer"))

    assert _said(qtbot, hearing) == "make her hair longer"


def test_a_phrase_the_verifying_listener_reads_differently_arrives_as_the_sentence_it_was(qtbot):
    # Said mid-thought, "undo the last one" is not the command its first word is.
    hearing = Hearing({"undo"}, engines=_engines(
        ["undo"], verifying_listener=lambda audio, hint: "undo the last one",
        take_down=lambda audio, hint: "undo the last one"))

    assert _said(qtbot, hearing) == "undo the last one"


def test_a_phrase_said_in_german_is_read_once_more_in_german_before_it_is_doubted(qtbot):
    hearing = Hearing({"genau"}, said_in={"genau": "de"}.get, engines=_engines(
        ["genau"], verifying_listener=lambda audio, hint: "Good night.",
        verifying_listener_in={"de": lambda audio, hint: "Genau."},
        take_down=lambda audio, hint: "good night"))

    assert _said(qtbot, hearing) == "genau"


def test_a_quiet_sound_with_no_words_in_it_is_not_worth_a_caption(qtbot):
    # The pause detector hears far quieter sounds than this app's own did, which is what
    # lets a quiet word through; a quiet nothing is a chair, not something to answer.
    faint = array.array("h", [400, -400] * 240).tobytes()
    engines = scripted_engines([said(""), said("")], take_down=lambda audio, hint: " . . . ",
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

    hearing = Hearing({"undo", "genau"}, said_in={"genau": "de"}.get)
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
    assert isinstance(engines.verifying_listener, WhisperReader)
    assert isinstance(engines.take_down, WhisperReader)
    assert engines.take_down is not engines.verifying_listener
    assert set(engines.verifying_listener_in) == {"de"}
    assert isinstance(engines.verifying_listener_in["de"], WhisperReader)
    # An utterance ends when its speaker pauses, however loud the room stays.
    assert isinstance(engines.hears_speech, HearsSpeech)
