"""VoiceWorker — transcribe the audio, rewrite the prompt pair, report the outcome.

The whisper/LLM calls are injected as plain functions, so the whole pipeline is
exercised synchronously without a mic, a model, or a server.
"""

from origenerator.voice.worker import VoiceWorker

_PROMPTS = {"positive": "a cat", "negative": ""}


def test_transcribes_then_rewrites_and_emits_the_new_pair(qtbot):
    worker = VoiceWorker(lambda audio: "make it a dog",
                         lambda pos, neg, instr: (f"{pos} -> {instr}", neg))
    out = []
    worker.rewritten.connect(out.append)

    worker.process(object(), _PROMPTS)

    assert out == [{"positive": "a cat -> make it a dog", "negative": ""}]


def test_heard_emits_the_transcription_for_on_screen_feedback(qtbot):
    worker = VoiceWorker(lambda audio: "make it a dog", lambda pos, neg, instr: (pos, neg))
    heard = []
    worker.heard.connect(heard.append)

    worker.process(object(), _PROMPTS)

    assert heard == ["make it a dog"]


def test_an_empty_transcription_is_a_failure_not_a_rewrite(qtbot):
    worker = VoiceWorker(lambda audio: "   ", lambda pos, neg, instr: ("x", "y"))
    fails, rewrites = [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)

    worker.process(object(), _PROMPTS)

    assert rewrites == [] and len(fails) == 1


def test_a_punctuation_only_transcription_is_a_failure(qtbot):
    # Whisper emits '. . . .' on noise; that must not trigger a (garbling) rewrite.
    worker = VoiceWorker(lambda audio: ". . . .", lambda pos, neg, instr: ("x", "y"))
    fails, rewrites = [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)

    worker.process(object(), _PROMPTS)

    assert rewrites == [] and len(fails) == 1


def test_a_rewrite_error_is_reported_not_raised(qtbot):
    def boom(pos, neg, instr):
        raise RuntimeError("no LLM server")

    worker = VoiceWorker(lambda audio: "make it a dog", boom)
    fails = []
    worker.failed.connect(fails.append)

    worker.process(object(), _PROMPTS)

    assert len(fails) == 1 and "no LLM server" in fails[0]


def _teeth_matcher(text):
    return "teeth" if "teeth" in text.lower() else None


def test_a_recognized_command_is_executed_not_rewritten(qtbot):
    # "Fix teeth" while a slideshow is up must not become a prompt edit.
    worker = VoiceWorker(lambda audio: "Fix teeth.", lambda pos, neg, instr: ("x", "y"))
    commands, rewrites = [], []
    worker.command.connect(commands.append)
    worker.rewritten.connect(rewrites.append)

    worker.process(object(), _PROMPTS, _teeth_matcher)

    assert commands == ["teeth"] and rewrites == []


def test_an_unmatched_utterance_still_rewrites(qtbot):
    worker = VoiceWorker(lambda audio: "make it a dog",
                         lambda pos, neg, instr: (f"{pos} -> {instr}", neg))
    out = []
    worker.rewritten.connect(out.append)

    worker.process(object(), _PROMPTS, _teeth_matcher)

    assert out == [{"positive": "a cat -> make it a dog", "negative": ""}]


def test_command_listening_alone_never_invents_a_rewrite(qtbot):
    # prompts is None while nothing is steering: an unmatched utterance simply
    # ends there — no rewrite, and nothing to report as a failure either.
    worker = VoiceWorker(lambda audio: "just chatting",
                         lambda pos, neg, instr: ("x", "y"))
    fails, rewrites, commands = [], [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)
    worker.command.connect(commands.append)

    worker.process(object(), None, _teeth_matcher)

    assert fails == [] and rewrites == [] and commands == []


def test_a_command_needs_no_prompts_at_all(qtbot):
    worker = VoiceWorker(lambda audio: "fix teeth", lambda pos, neg, instr: ("x", "y"))
    commands = []
    worker.command.connect(commands.append)

    worker.process(object(), None, _teeth_matcher)

    assert commands == ["teeth"]
