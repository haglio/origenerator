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
