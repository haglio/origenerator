"""VoiceSteering — always-listening: each utterance rewrites the prompt pair.

An injected listener (a fake mic that says text) and an inline worker (a faked
rewrite) drive the whole flow synchronously, without audio, a model, or a server.
"""
from __future__ import annotations

from unittest.mock import Mock

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.voice.steering import VoiceSteering
from origenerator.voice.worker import VoiceWorker


class FakeListener(QObject):
    said = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, says="no hat"):
        super().__init__()
        self.says = says
        self.started = False
        self.stopped = False

    def hear(self):
        self.said.emit(self.says)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _steering(rewrite=None, listener=None):
    listener = listener if listener is not None else FakeListener()
    worker = VoiceWorker(rewrite or (lambda pos, neg, instr: (f"{pos}, {instr}", neg)))
    return VoiceSteering(listener=listener, worker=worker), listener


def test_an_utterance_rewrites_the_prompt_pair_in_place(qtbot):
    steering, listener = _steering()
    prompts = {"positive": "a woman", "negative": ""}
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    assert listener.started
    listener.hear()

    assert prompts["positive"] == "a woman, no hat"


def test_stop_ends_listening_and_ignores_later_utterances(qtbot):
    steering, listener = _steering()
    prompts = {"positive": "a woman", "negative": ""}
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    steering.stop()
    listener.hear()  # a late callback after stop

    assert listener.stopped
    assert prompts["positive"] == "a woman"  # ignored


def test_a_rewrite_error_surfaces(qtbot):
    def boom(pos, neg, instr):
        raise RuntimeError("no LLM server")

    steering, listener = _steering(rewrite=boom)
    errors = []
    steering.error.connect(errors.append)
    steering.start(lambda: {"positive": "a woman", "negative": ""}, lambda new: None)

    listener.hear()

    assert errors and "no LLM server" in errors[0]


def test_a_listener_failure_surfaces(qtbot):
    steering, listener = _steering()
    errors = []
    steering.error.connect(errors.append)
    steering.start(lambda: {"positive": "a woman", "negative": ""}, lambda new: None)

    listener.failed.emit("no mic")

    assert errors and "no mic" in errors[0]


# --- spoken commands: the same mic, a second use ----------------------------


def _command_steering(says="fix teeth"):
    listener = FakeListener(says)
    worker = VoiceWorker(lambda pos, neg, instr: (f"{pos}, {instr}", neg))
    steering = VoiceSteering(
        listener=listener, worker=worker,
        command_matcher=lambda text: "teeth" if "teeth" in text.lower() else None,
    )
    return steering, listener


def test_commands_alone_open_the_mic_and_execute_what_they_match(qtbot):
    steering, listener = _command_steering()
    ran = []
    steering.start_commands(ran.append)

    assert listener.started
    listener.hear()

    assert ran == ["teeth"]


def test_a_matched_command_is_consumed_not_steered(qtbot):
    # With a loop steering AND a surface listening, "fix teeth" is a command —
    # it must not also (or instead) rewrite the prompt.
    steering, listener = _command_steering()
    prompts = {"positive": "a woman", "negative": ""}
    ran = []
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))
    steering.start_commands(ran.append)

    listener.hear()

    assert ran == ["teeth"]
    assert prompts["positive"] == "a woman"


def test_an_unmatched_utterance_still_steers_the_prompt(qtbot):
    steering, listener = _command_steering(says="no hat")
    prompts = {"positive": "a woman", "negative": ""}
    ran = []
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))
    steering.start_commands(ran.append)

    listener.hear()

    assert ran == []
    assert prompts["positive"] == "a woman, no hat"


def test_the_mic_stays_open_while_either_use_still_wants_it(qtbot):
    steering, listener = _command_steering()
    steering.start(lambda: {"positive": "", "negative": ""}, lambda new: None)
    steering.start_commands(lambda part: None)

    steering.stop()  # the loop ended; a slideshow is still up
    assert not listener.stopped

    steering.stop_commands()  # now nothing wants the mic
    assert listener.stopped


def test_left_to_itself_it_listens_for_the_phrases_it_was_given(qtbot, monkeypatch):
    built = Mock()
    monkeypatch.setattr("origenerator.voice.steering.Hearing", built)

    VoiceSteering(phrases={"fix teeth", "mic off"}, never_repaired={"mic off"})

    built.assert_called_once_with({"fix teeth", "mic off"}, never_repaired={"mic off"})


def test_stopping_commands_ends_their_execution(qtbot):
    steering, listener = _command_steering()
    ran = []
    steering.start_commands(ran.append)
    steering.stop_commands()

    listener.hear()  # a late utterance after the surface closed

    assert ran == []
    assert listener.stopped


# --- spoken requests: a third use of the same mic ----------------------------


def _request_steering(says="Request, no hat, over."):
    from origenerator.voice.dictation import RequestDictation

    listener = FakeListener(says)
    worker = VoiceWorker(lambda pos, neg, instr: (f"{pos}, {instr}", neg))
    steering = VoiceSteering(
        listener=listener, worker=worker, dictation=RequestDictation(),
        command_matcher=lambda text: "teeth" if "teeth" in text.lower() else None,
    )
    return steering, listener


def test_a_request_is_re_emitted_rather_than_steering_the_prompt(qtbot):
    steering, listener = _request_steering()
    prompts = {"positive": "a woman", "negative": ""}
    spoken = []
    steering.request.connect(spoken.append)
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    listener.hear()

    assert [s.text for s in spoken] == ["no hat"]
    assert prompts["positive"] == "a woman"  # not also rewritten


def test_an_open_request_swallows_what_would_be_a_command(qtbot):
    # The words of a request are a sentence, not instructions: "fix teeth" said
    # inside one belongs to the request.
    steering, listener = _request_steering(says="Request.")
    ran = []
    spoken = []
    steering.request.connect(spoken.append)
    steering.start_commands(ran.append)

    listener.hear()          # opens the request
    listener.says = "fix teeth"
    listener.hear()

    assert ran == []
    assert len(spoken) == 2


def test_requests_ride_along_wherever_the_mic_is_open(qtbot):
    # Unlike "fix …", which means something only over a fullscreen surface, a
    # request can be spoken any time the mic is listening at all.
    steering, listener = _request_steering()
    spoken = []
    steering.request.connect(spoken.append)
    steering.start(lambda: {"positive": "", "negative": ""}, lambda new: None)

    listener.hear()

    assert spoken and spoken[0].text == "no hat"


def test_closing_the_mic_drops_a_half_said_request(qtbot):
    steering, listener = _request_steering(says="Request.")
    steering.start_commands(lambda part: None)
    listener.hear()
    assert steering._dictation.listening

    steering.stop_commands()

    assert not steering._dictation.listening


# --- the bare vocabulary, which outranks an opening request ------------------


def _bare_steering(says):
    """Steering wired as the gallery wires it: a dictation, a loose matcher, and
    a strict whole-utterance one that gets its say before a request can open."""
    from origenerator.voice.dictation import RequestDictation

    listener = FakeListener(says)
    worker = VoiceWorker(lambda pos, neg, instr: (f"{pos}, {instr}", neg))
    steering = VoiceSteering(
        listener=listener, worker=worker, dictation=RequestDictation(),
        command_matcher=lambda text: "teeth" if "teeth" in text.lower() else None,
        bare_matcher=lambda text: (
            text.strip().lower() if text.strip().lower() in ("requests", "weird") else None
        ),
    )
    return steering, listener


def test_a_bare_command_word_beats_an_opening_request(qtbot):
    # "requests" is a shelf and "request" opens a dictation; whole and alone,
    # the word is the command — otherwise the shelf would be unreachable.
    steering, listener = _bare_steering("requests")
    ran, spoken = [], []
    steering.request.connect(spoken.append)
    steering.start_commands(ran.append)

    listener.hear()

    assert ran == ["requests"]
    assert spoken == []
    assert not steering._dictation.listening


def test_an_open_request_takes_the_word_back(qtbot):
    # Mid-sentence the dictation is in front again: a command word said inside a
    # request is one of the request's words, not an order.
    steering, listener = _bare_steering("Request.")
    ran, spoken = [], []
    steering.request.connect(spoken.append)
    steering.start_commands(ran.append)

    listener.hear()          # opens the request
    listener.says = "requests"
    listener.hear()

    assert ran == []
    assert len(spoken) == 2


def test_a_bare_command_needs_a_surface_listening_for_commands(qtbot):
    # With a loop steering and nothing listening for commands, the word is not a
    # command — it steers, like anything else both matchers decline.
    steering, listener = _bare_steering("weird")
    prompts = {"positive": "a woman", "negative": ""}
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    listener.hear()

    assert prompts["positive"] == "a woman, weird"


def test_a_mic_that_will_not_open_says_what_stopped_it(qtbot):
    steering, listener = _steering()
    errors = []
    steering.error.connect(errors.append)
    steering.start_commands(lambda part: None)

    listener.failed.emit("No module named 'sounddevice'")

    assert errors == ["mic unavailable — No module named 'sounddevice'"]
