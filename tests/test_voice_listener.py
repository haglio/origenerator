from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest
from shared_ui.testing import appending_to

from origenerator.voice.dictation import RequestDictation
from origenerator.voice.listener import CommandAndRequestListener, Phrases
from tests.conftest import FakeCommandAndRequestListener, FakeHearing


def _listener(says="fix teeth"):
    hearing = FakeHearing(says)
    listener = CommandAndRequestListener(
        hearing=hearing,
        command_matcher=lambda text: "teeth" if "teeth" in text.lower() else None,
    )
    return listener, hearing


def _into(ran):
    return lambda matched, said_at: ran.append(matched)


def _ignore(matched, said_at):
    return None


def test_a_command_goes_with_when_the_mic_heard_it_said(qtbot):
    listener, hearing = _listener()
    ran = []
    listener.start_commands(lambda matched, said_at: ran.append((matched, said_at)))

    hearing.hear(spoken_at=7.5)

    assert ran == [("teeth", 7.5)]


def test_commands_open_the_mic_and_execute_what_they_match(qtbot):
    listener, hearing = _listener()
    ran = []
    listener.start_commands(_into(ran))

    assert hearing.started
    hearing.hear()

    assert ran == ["teeth"]


def test_words_that_are_no_command_and_no_request_do_nothing(qtbot):
    listener, hearing = _listener(says="make it a dog")
    ran, requests, errors = [], [], []
    listener.request.connect(appending_to(requests))
    listener.error.connect(appending_to(errors))
    listener.start_commands(_into(ran))

    hearing.hear()

    assert (ran, requests, errors) == ([], [], [])


@pytest.mark.parametrize("noise", ["   ", ". . . ."])
def test_a_sound_with_no_words_in_it_is_answered_as_not_caught(qtbot, noise):
    # Whisper writes '. . . .' for noise.
    listener, hearing = _listener(says=noise)
    ran, errors = [], []
    listener.error.connect(appending_to(errors))
    listener.start_commands(_into(ran))

    hearing.hear()

    assert (ran, errors) == ([], ["Didn't catch that."])


def test_a_sound_with_no_words_in_it_is_logged_as_information_not_a_warning(qtbot, caplog):
    listener, hearing = _listener(says=". . . .")
    listener.start_commands(_ignore)

    with caplog.at_level(logging.DEBUG):
        hearing.hear()

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.INFO, "Voice: a sound with no words in it")]


def test_left_to_itself_it_listens_for_the_phrases_it_was_given(qtbot, monkeypatch):
    built = Mock()
    monkeypatch.setattr("origenerator.voice.listener.Hearing", built)

    said_in = {"genau": "de"}.get

    CommandAndRequestListener(
        phrases=Phrases({"fix teeth", "mic off"}, {"mic off"}, said_in))

    assert built.call_args_list == [
        (({"fix teeth", "mic off"},), {"never_repaired": {"mic off"}, "said_in": said_in})], (
        "the phrases are the vocabulary said outright, which the mic hears fast and exactly; "
        "everything else reaches the same matchers as a sentence taken down")


def test_a_command_is_logged_by_what_it_matched_and_how_many_words_it_was(qtbot, caplog):
    listener, hearing = _listener(says="please fix the teeth on this one")
    listener.start_commands(_ignore)

    with caplog.at_level(logging.DEBUG):
        hearing.hear()

    assert caplog.messages == ["Voice: a 7-word utterance matched 'teeth'"]


def test_words_that_miss_every_command_go_to_the_screen_and_only_their_count_to_the_log(
        qtbot, caplog):
    listener, hearing = _listener(says="put the kettle on")
    listener.start_commands(_ignore)
    shown = []
    listener.heard.connect(appending_to(shown))

    with caplog.at_level(logging.DEBUG):
        hearing.hear()

    assert shown == ["put the kettle on"]
    assert caplog.messages == ["Voice: a 4-word utterance matched no command"]


def test_stopping_commands_ends_their_execution(qtbot):
    listener, hearing = _listener()
    ran = []
    listener.start_commands(_into(ran))
    listener.stop_commands()

    hearing.hear()

    assert ran == []
    assert hearing.stopped
    assert not hearing.closed


def test_closing_ends_the_commands_and_waits_for_the_microphone_to_close(qtbot):
    listener, hearing = _listener()
    ran = []
    listener.start_commands(_into(ran))
    listener.close()

    hearing.hear()

    assert ran == []
    assert hearing.closed



def _request_listener(says="Request, no hat, over."):
    hearing = FakeHearing(says)
    listener = CommandAndRequestListener(
        hearing=hearing, dictation=RequestDictation(),
        command_matcher=lambda text: "teeth" if "teeth" in text.lower() else None,
    )
    return listener, hearing


def test_a_request_is_re_emitted(qtbot):
    listener, hearing = _request_listener()
    spoken = []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_ignore)

    hearing.hear()

    assert [s.text for s in spoken] == ["no hat"]


def test_a_request_keeps_the_time_the_mic_heard_its_first_step_said(qtbot):
    listener, hearing = _request_listener()
    spoken = []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_ignore)

    hearing.hear(spoken_at=7.5)

    assert [s.opened_at for s in spoken] == [7.5]


def test_a_request_the_session_heard_keeps_when_it_was_said(qtbot):
    listener, _hearing = _request_listener()

    spoken = listener.push_dictation("Request, no hat, over.", spoken_at=7.5)

    assert spoken.opened_at == 7.5


def test_an_open_request_swallows_what_would_be_a_command(qtbot):
    listener, hearing = _request_listener(says="Request.")
    ran = []
    spoken = []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_into(ran))

    hearing.hear()
    hearing.says = "fix teeth"
    hearing.hear()

    assert ran == []
    assert len(spoken) == 2


def test_a_request_is_logged_by_where_it_stands_and_never_by_its_words(qtbot, caplog):
    listener, hearing = _request_listener(says="Request, no example lantern, over.")
    spoken = []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_ignore)

    with caplog.at_level(logging.INFO, logger="origenerator.voice"):
        hearing.hear()

    assert [request.text for request in spoken] == ["no example lantern"]
    assert caplog.messages == ["Voice: request completed"]


def test_closing_the_mic_drops_a_half_said_request(qtbot):
    listener, hearing = _request_listener(says="Request.")
    listener.start_commands(_ignore)
    hearing.hear()
    assert listener.taking_a_request

    listener.stop_commands()

    assert not listener.taking_a_request



_BOTH_VOCABULARIES = {
    "command_matcher": lambda text: "teeth" if "teeth" in text.lower() else None,
    "bare_matcher": lambda text: (
        text.strip().lower() if text.strip().lower() in ("requests", "trash", "fix teeth")
        else None
    ),
}


def _bare_listener(says):
    hearing = FakeHearing(says)
    listener = CommandAndRequestListener(
        hearing=hearing, dictation=RequestDictation(), **_BOTH_VOCABULARIES)
    return listener, hearing


def test_a_word_a_request_opens_on_opens_one_whatever_else_it_matches(qtbot):
    listener, hearing = _bare_listener("requests")
    ran, spoken = [], []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_into(ran))

    hearing.hear()

    assert ran == []
    assert len(spoken) == 1
    assert listener.taking_a_request


def test_a_bare_command_word_is_the_command(qtbot):
    listener, hearing = _bare_listener("trash")
    ran, spoken = [], []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_into(ran))

    hearing.hear()

    assert ran == ["trash"]
    assert spoken == []


def test_an_open_request_takes_the_word_back(qtbot):
    listener, hearing = _bare_listener("Request.")
    ran, spoken = [], []
    listener.request.connect(appending_to(spoken))
    listener.start_commands(_into(ran))

    hearing.hear()
    hearing.says = "requests"
    hearing.hear()

    assert ran == []
    assert len(spoken) == 2


def _routes(listener, say, utterances):
    taken = []
    listener.request.connect(lambda spoken: taken.append(("request", spoken.state, spoken.text)))
    listener.start_commands(lambda matched, *_said_at: taken.append(("command", matched)))
    for utterance in utterances:
        say(utterance)
    return taken


@pytest.mark.parametrize("utterances", [
    ["requests"], ["trash"], ["fix teeth"], ["Request, fix teeth, over."],
    ["Request.", "trash", "over"],
])
def test_the_suites_stand_in_routes_what_it_hears_as_the_listener_does(qtbot, utterances):
    hearing = FakeHearing()
    listener = CommandAndRequestListener(
        hearing=hearing, dictation=RequestDictation(), **_BOTH_VOCABULARIES)
    stand_in = FakeCommandAndRequestListener(dictation=RequestDictation(), **_BOTH_VOCABULARIES)

    def into_the_mic(utterance):
        hearing.says = utterance
        hearing.hear()

    assert _routes(stand_in, stand_in.speak, utterances) == _routes(
        listener, into_the_mic, utterances), (
        "the voice tests hear through the suite's stand-in listener, so it routes an utterance "
        "in the listener's own order: an open or opening request first, then the "
        "whole-utterance commands, then the looser matcher")


def test_a_mic_that_will_not_open_says_what_stopped_it(qtbot):
    listener, hearing = _listener()
    errors = []
    listener.error.connect(appending_to(errors))
    listener.start_commands(_ignore)

    hearing.failed.emit("No module named 'sounddevice'")

    assert errors == ["mic unavailable — No module named 'sounddevice'"]


def test_a_mic_that_will_not_open_is_logged_as_a_warning(qtbot, caplog):
    listener, hearing = _listener()
    listener.start_commands(_ignore)

    with caplog.at_level(logging.DEBUG):
        hearing.failed.emit("No module named 'sounddevice'")

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "Voice: mic unavailable — No module named 'sounddevice'")]


def test_a_request_opened_at_the_mic_is_finished_by_what_the_session_heard(qtbot):
    listener, hearing = _request_listener(says="Request, a red scarf")
    listener.start_commands(_ignore)

    hearing.hear()
    finished = listener.push_dictation("on a snowy hill, over")

    assert getattr(finished, "text", None) == "a red scarf on a snowy hill", (
        "the mic's half and the session's half of one request are one dictation")


def test_it_says_a_request_is_being_taken_from_its_opening_word_until_over(qtbot):
    listener, _hearing = _bare_listener("unused")

    listener.push_dictation("request")
    taking_one = listener.taking_a_request
    listener.push_dictation("a red scarf over")

    assert (taking_one, listener.taking_a_request) == (True, False)
