"""CommandAndRequestListener — what the open mic hears: a command, a request, or nothing.

An injected microphone that says text drives the whole flow synchronously, with
no audio and no model.
"""
from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from origenerator.voice.dictation import RequestDictation
from origenerator.voice.listener import CommandAndRequestListener
from tests.conftest import FakeHearing


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
    listener.request.connect(requests.append)
    listener.error.connect(errors.append)
    listener.start_commands(_into(ran))

    hearing.hear()

    assert (ran, requests, errors) == ([], [], [])


@pytest.mark.parametrize("noise", ["   ", ". . . ."])
def test_a_sound_with_no_words_in_it_is_answered_as_not_caught(qtbot, noise):
    # Whisper writes '. . . .' for noise; it is neither a command nor nothing.
    listener, hearing = _listener(says=noise)
    ran, errors = [], []
    listener.error.connect(errors.append)
    listener.start_commands(_into(ran))

    hearing.hear()

    assert (ran, errors) == ([], ["Didn't catch that."])


def test_left_to_itself_it_listens_for_the_phrases_it_was_given(qtbot, monkeypatch):
    built = Mock()
    monkeypatch.setattr("origenerator.voice.listener.Hearing", built)

    said_in = {"genau": "de"}.get

    CommandAndRequestListener(phrases={"fix teeth", "mic off"}, never_repaired={"mic off"},
                              said_in=said_in)

    built.assert_called_once_with({"fix teeth", "mic off"}, never_repaired={"mic off"},
                                  said_in=said_in)


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
    listener.heard.connect(shown.append)

    with caplog.at_level(logging.DEBUG):
        hearing.hear()

    assert shown == ["put the kettle on"]
    assert caplog.messages == ["Voice: a 4-word utterance matched no command"]


def test_stopping_commands_ends_their_execution(qtbot):
    listener, hearing = _listener()
    ran = []
    listener.start_commands(_into(ran))
    listener.stop_commands()

    hearing.hear()  # a late utterance after the mic was shut

    assert ran == []
    assert hearing.stopped


# --- spoken requests: "Request … over" on the same mic ----------------------


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
    listener.request.connect(spoken.append)
    listener.start_commands(_ignore)

    hearing.hear()

    assert [s.text for s in spoken] == ["no hat"]


def test_a_request_keeps_the_time_the_mic_heard_its_first_step_said(qtbot):
    listener, hearing = _request_listener()
    spoken = []
    listener.request.connect(spoken.append)
    listener.start_commands(_ignore)

    hearing.hear(spoken_at=7.5)

    assert [s.opened_at for s in spoken] == [7.5]


def test_a_request_the_session_heard_keeps_when_it_was_said(qtbot):
    listener, _hearing = _request_listener()

    spoken = listener.push_dictation("Request, no hat, over.", spoken_at=7.5)

    assert spoken.opened_at == 7.5


def test_an_open_request_swallows_what_would_be_a_command(qtbot):
    # The words of a request are a sentence, not instructions: "fix teeth" said
    # inside one belongs to the request.
    listener, hearing = _request_listener(says="Request.")
    ran = []
    spoken = []
    listener.request.connect(spoken.append)
    listener.start_commands(_into(ran))

    hearing.hear()          # opens the request
    hearing.says = "fix teeth"
    hearing.hear()

    assert ran == []
    assert len(spoken) == 2


def test_a_request_is_logged_by_where_it_stands_and_never_by_its_words(qtbot, caplog):
    listener, hearing = _request_listener(says="Request, no example lantern, over.")
    spoken = []
    listener.request.connect(spoken.append)
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


# --- the bare vocabulary, asked once the request has passed -------------------


def _bare_listener(says):
    """A listener wired as the gallery wires it: a dictation, a loose matcher,
    and a strict whole-utterance one."""
    hearing = FakeHearing(says)
    listener = CommandAndRequestListener(
        hearing=hearing, dictation=RequestDictation(),
        command_matcher=lambda text: "teeth" if "teeth" in text.lower() else None,
        bare_matcher=lambda text: (
            text.strip().lower() if text.strip().lower() in ("requests", "weird") else None
        ),
    )
    return listener, hearing


def test_a_word_a_request_opens_on_opens_one_whatever_else_it_matches(qtbot):
    listener, hearing = _bare_listener("requests")
    ran, spoken = [], []
    listener.request.connect(spoken.append)
    listener.start_commands(_into(ran))

    hearing.hear()

    assert ran == []
    assert len(spoken) == 1
    assert listener.taking_a_request


def test_a_bare_command_word_is_the_command(qtbot):
    listener, hearing = _bare_listener("weird")
    ran, spoken = [], []
    listener.request.connect(spoken.append)
    listener.start_commands(_into(ran))

    hearing.hear()

    assert ran == ["weird"]
    assert spoken == []


def test_an_open_request_takes_the_word_back(qtbot):
    # Mid-sentence the dictation is in front again: a command word said inside a
    # request is one of the request's words, not an order.
    listener, hearing = _bare_listener("Request.")
    ran, spoken = [], []
    listener.request.connect(spoken.append)
    listener.start_commands(_into(ran))

    hearing.hear()          # opens the request
    hearing.says = "requests"
    hearing.hear()

    assert ran == []
    assert len(spoken) == 2


def test_a_mic_that_will_not_open_says_what_stopped_it(qtbot):
    listener, hearing = _listener()
    errors = []
    listener.error.connect(errors.append)
    listener.start_commands(_ignore)

    hearing.failed.emit("No module named 'sounddevice'")

    assert errors == ["mic unavailable — No module named 'sounddevice'"]


def test_it_says_a_request_is_being_taken_from_its_opening_word_until_over(qtbot):
    listener, _hearing = _bare_listener("unused")

    listener.push_dictation("request")
    taking_one = listener.taking_a_request
    listener.push_dictation("a red scarf over")

    assert (taking_one, listener.taking_a_request) == (True, False)
