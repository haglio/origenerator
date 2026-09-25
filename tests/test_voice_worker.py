"""VoiceWorker — read what was said, rewrite the prompt pair, report the outcome.

The LLM call is injected as a plain function, so the whole pipeline is exercised
synchronously without a model or a server.
"""
from __future__ import annotations

from PyQt6 import sip

from origenerator.voice.worker import ProcessTask, VoiceWorker

_PROMPTS = {"positive": "a cat", "negative": ""}


def test_what_was_said_rewrites_the_pair_and_the_new_one_is_emitted(qtbot):
    worker = VoiceWorker(lambda pos, neg, instr: (f"{pos} -> {instr}", neg))
    out = []
    worker.rewritten.connect(out.append)

    worker.process("make it a dog", _PROMPTS)

    assert out == [{"positive": "a cat -> make it a dog", "negative": ""}]


def test_heard_emits_what_was_said_for_on_screen_feedback(qtbot):
    worker = VoiceWorker(lambda pos, neg, instr: (pos, neg))
    heard = []
    worker.heard.connect(heard.append)

    worker.process("make it a dog", _PROMPTS)

    assert heard == ["make it a dog"]


def test_nothing_said_is_a_failure_not_a_rewrite(qtbot):
    worker = VoiceWorker(lambda pos, neg, instr: ("x", "y"))
    fails, rewrites = [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)

    worker.process("   ", _PROMPTS)

    assert rewrites == [] and len(fails) == 1


def test_punctuation_alone_is_a_failure(qtbot):
    # Whisper emits '. . . .' on noise; that must not trigger a (garbling) rewrite.
    worker = VoiceWorker(lambda pos, neg, instr: ("x", "y"))
    fails, rewrites = [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)

    worker.process(". . . .", _PROMPTS)

    assert rewrites == [] and len(fails) == 1


def test_a_rewrite_error_is_reported_not_raised(qtbot):
    def boom(pos, neg, instr):
        raise RuntimeError("no LLM server")

    worker = VoiceWorker(boom)
    fails = []
    worker.failed.connect(fails.append)

    worker.process("make it a dog", _PROMPTS)

    assert len(fails) == 1 and "no LLM server" in fails[0]


def _teeth_matcher(text):
    return "teeth" if "teeth" in text.lower() else None


def test_a_recognized_command_is_executed_not_rewritten(qtbot):
    # "Fix teeth" while a slideshow is up must not become a prompt edit.
    worker = VoiceWorker(lambda pos, neg, instr: ("x", "y"))
    commands, rewrites = [], []
    worker.command.connect(commands.append)
    worker.rewritten.connect(rewrites.append)

    worker.process("Fix teeth.", _PROMPTS, _teeth_matcher)

    assert commands == ["teeth"] and rewrites == []


def test_an_unmatched_utterance_still_rewrites(qtbot):
    worker = VoiceWorker(lambda pos, neg, instr: (f"{pos} -> {instr}", neg))
    out = []
    worker.rewritten.connect(out.append)

    worker.process("make it a dog", _PROMPTS, _teeth_matcher)

    assert out == [{"positive": "a cat -> make it a dog", "negative": ""}]


def test_command_listening_alone_never_invents_a_rewrite(qtbot):
    # prompts is None while nothing is steering: an unmatched utterance simply
    # ends there — no rewrite, and nothing to report as a failure either.
    worker = VoiceWorker(lambda pos, neg, instr: ("x", "y"))
    fails, rewrites, commands = [], [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)
    worker.command.connect(commands.append)

    worker.process("just chatting", None, _teeth_matcher)

    assert fails == [] and rewrites == [] and commands == []


def test_a_command_needs_no_prompts_at_all(qtbot):
    worker = VoiceWorker(lambda pos, neg, instr: ("x", "y"))
    commands = []
    worker.command.connect(commands.append)

    worker.process("fix teeth", None, _teeth_matcher)

    assert commands == ["teeth"]


def test_an_utterance_whose_worker_the_app_took_on_its_way_out_is_let_go_of(qtbot):
    worker = VoiceWorker(lambda pos, neg, instr: (pos, neg))
    sip.delete(worker)  # what the interpreter's exit does to a worker still answering

    ProcessTask(worker, "make it a dog", _PROMPTS).run()
