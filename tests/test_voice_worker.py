"""VoiceWorker — transcribe the audio, rewrite the prompt, report the outcome.

The recorder and whisper/LLM calls are injected as plain functions, so the whole
pipeline is exercised synchronously without a mic, a model, or a server.
"""

from origenerator.gui.voice_button import VoiceWorker


def test_transcribes_then_rewrites_and_emits_the_new_prompt(qtbot):
    worker = VoiceWorker(lambda audio: "make it a dog", lambda cur, instr: f"{cur} -> {instr}")
    out = []
    worker.rewritten.connect(out.append)

    worker.process(object(), "a cat")

    assert out == ["a cat -> make it a dog"]


def test_an_empty_transcription_is_a_failure_not_a_rewrite(qtbot):
    worker = VoiceWorker(lambda audio: "   ", lambda cur, instr: "should not run")
    fails, rewrites = [], []
    worker.failed.connect(fails.append)
    worker.rewritten.connect(rewrites.append)

    worker.process(object(), "a cat")

    assert rewrites == [] and len(fails) == 1


def test_a_rewrite_error_is_reported_not_raised(qtbot):
    def boom(cur, instr):
        raise RuntimeError("no LLM server")

    worker = VoiceWorker(lambda audio: "make it a dog", boom)
    fails = []
    worker.failed.connect(fails.append)

    worker.process(object(), "a cat")

    assert len(fails) == 1 and "no LLM server" in fails[0]


def test_busy_toggles_around_the_work(qtbot):
    worker = VoiceWorker(lambda audio: "go", lambda cur, instr: "new")
    states = []
    worker.busy.connect(states.append)

    worker.process(object(), "a cat")

    assert states == [True, False]
