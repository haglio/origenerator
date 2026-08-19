"""VoiceSteering — always-listening: each utterance rewrites the prompt pair.

An injected listener (a fake mic) and an inline worker (faked transcribe/rewrite)
drive the whole flow synchronously, without audio, a model, or a server.
"""

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.voice.steering import VoiceSteering
from origenerator.voice.worker import VoiceWorker


class FakeListener(QObject):
    utterance = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _steering(transcribe=None, rewrite=None, listener=None):
    listener = listener if listener is not None else FakeListener()
    worker = VoiceWorker(
        transcribe or (lambda audio: "no hat"),
        rewrite or (lambda pos, neg, instr: (f"{pos}, {instr}", neg)),
    )
    return VoiceSteering(listener=listener, worker=worker), listener


def test_an_utterance_rewrites_the_prompt_pair_in_place(qtbot):
    steering, listener = _steering()
    prompts = {"positive": "a woman", "negative": ""}
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    assert listener.started
    listener.utterance.emit(object())

    assert prompts["positive"] == "a woman, no hat"


def test_stop_ends_listening_and_ignores_later_utterances(qtbot):
    steering, listener = _steering()
    prompts = {"positive": "a woman", "negative": ""}
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    steering.stop()
    listener.utterance.emit(object())  # a late callback after stop

    assert listener.stopped
    assert prompts["positive"] == "a woman"  # ignored


def test_a_rewrite_error_surfaces(qtbot):
    def boom(pos, neg, instr):
        raise RuntimeError("no LLM server")

    steering, listener = _steering(rewrite=boom)
    errors = []
    steering.error.connect(errors.append)
    steering.start(lambda: {"positive": "a woman", "negative": ""}, lambda new: None)

    listener.utterance.emit(object())

    assert errors and "no LLM server" in errors[0]


def test_a_listener_failure_surfaces(qtbot):
    class BrokenListener(QObject):
        utterance = pyqtSignal(object)

        def start(self):
            raise RuntimeError("no mic")

        def stop(self):
            pass

    steering, _ = _steering(listener=BrokenListener())
    errors = []
    steering.error.connect(errors.append)

    steering.start(lambda: {"positive": "a woman", "negative": ""}, lambda new: None)

    assert errors and "no mic" in errors[0]


# --- spoken commands: the same mic, a second use ----------------------------


def _command_steering(transcribe="fix teeth"):
    listener = FakeListener()
    worker = VoiceWorker(lambda audio: transcribe,
                         lambda pos, neg, instr: (f"{pos}, {instr}", neg))
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
    listener.utterance.emit(object())

    assert ran == ["teeth"]


def test_a_matched_command_is_consumed_not_steered(qtbot):
    # With a loop steering AND a surface listening, "fix teeth" is a command —
    # it must not also (or instead) rewrite the prompt.
    steering, listener = _command_steering()
    prompts = {"positive": "a woman", "negative": ""}
    ran = []
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))
    steering.start_commands(ran.append)

    listener.utterance.emit(object())

    assert ran == ["teeth"]
    assert prompts["positive"] == "a woman"


def test_an_unmatched_utterance_still_steers_the_prompt(qtbot):
    steering, listener = _command_steering(transcribe="no hat")
    prompts = {"positive": "a woman", "negative": ""}
    ran = []
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))
    steering.start_commands(ran.append)

    listener.utterance.emit(object())

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


def test_the_transcribe_bias_reaches_the_transcriber(qtbot):
    # The vocabulary bias only helps if the real worker's transcriber holds it.
    steering = VoiceSteering(listener=FakeListener(),
                             transcribe_bias="Voice commands: fix.")
    assert steering._transcriber._prompt_bias == "Voice commands: fix."


def test_stopping_commands_ends_their_execution(qtbot):
    steering, listener = _command_steering()
    ran = []
    steering.start_commands(ran.append)
    steering.stop_commands()

    listener.utterance.emit(object())  # a late utterance after the surface closed

    assert ran == []
    assert listener.stopped


# --- spoken requests: a third use of the same mic ----------------------------


def _request_steering(transcribe="Request, no hat, over."):
    from origenerator.voice.dictation import RequestDictation

    listener = FakeListener()
    worker = VoiceWorker(lambda audio: transcribe,
                         lambda pos, neg, instr: (f"{pos}, {instr}", neg))
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

    listener.utterance.emit(object())

    assert [s.text for s in spoken] == ["no hat"]
    assert prompts["positive"] == "a woman"  # not also rewritten


def test_an_open_request_swallows_what_would_be_a_command(qtbot):
    # The words of a request are a sentence, not instructions: "fix teeth" said
    # inside one belongs to the request.
    steering, listener = _request_steering(transcribe="Request.")
    ran = []
    spoken = []
    steering.request.connect(spoken.append)
    steering.start_commands(ran.append)

    listener.utterance.emit(object())          # opens the request
    steering._worker._transcribe = lambda audio: "fix teeth"
    listener.utterance.emit(object())

    assert ran == []
    assert len(spoken) == 2


def test_requests_ride_along_wherever_the_mic_is_open(qtbot):
    # Unlike "fix …", which means something only over a fullscreen surface, a
    # request can be spoken any time the mic is listening at all.
    steering, listener = _request_steering()
    spoken = []
    steering.request.connect(spoken.append)
    steering.start(lambda: {"positive": "", "negative": ""}, lambda new: None)

    listener.utterance.emit(object())

    assert spoken and spoken[0].text == "no hat"


def test_closing_the_mic_drops_a_half_said_request(qtbot):
    steering, listener = _request_steering(transcribe="Request.")
    steering.start_commands(lambda part: None)
    listener.utterance.emit(object())
    assert steering._dictation.listening

    steering.stop_commands()

    assert not steering._dictation.listening


# --- the bare vocabulary, which outranks an opening request ------------------


def _bare_steering(transcribe):
    """Steering wired as the gallery wires it: a dictation, a loose matcher, and
    a strict whole-utterance one that gets its say before a request can open."""
    from origenerator.voice.dictation import RequestDictation

    listener = FakeListener()
    worker = VoiceWorker(lambda audio: transcribe,
                         lambda pos, neg, instr: (f"{pos}, {instr}", neg))
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

    listener.utterance.emit(object())

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

    listener.utterance.emit(object())          # opens the request
    steering._worker._transcribe = lambda audio: "requests"
    listener.utterance.emit(object())

    assert ran == []
    assert len(spoken) == 2


def test_a_bare_command_needs_a_surface_listening_for_commands(qtbot):
    # With a loop steering and nothing listening for commands, the word is not a
    # command — it steers, like anything else both matchers decline.
    steering, listener = _bare_steering("weird")
    prompts = {"positive": "a woman", "negative": ""}
    steering.start(lambda: dict(prompts), lambda new: prompts.update(new))

    listener.utterance.emit(object())

    assert prompts["positive"] == "a woman, weird"


def test_a_mic_that_will_not_open_says_what_stopped_it(qtbot):
    class BrokenListener(QObject):
        utterance = pyqtSignal(object)

        def start(self):
            raise RuntimeError("No module named 'sounddevice'")

        def stop(self):
            pass

    steering, _ = _steering(listener=BrokenListener())
    errors = []
    steering.error.connect(errors.append)

    steering.start_commands(lambda part: None)

    assert errors and "mic unavailable" in errors[0]
