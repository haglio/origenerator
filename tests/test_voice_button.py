"""VoiceButton — hold to record, release to transcribe → rewrite → update prompt.

A fake recorder and an injected (same-thread) worker make press/release drive the
whole pipeline synchronously, with no mic, model, server, or background thread.
"""

from origenerator.gui.voice_button import VoiceButton, VoiceWorker


class FakeRecorder:
    def __init__(self, audio):
        self._audio = audio
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return self._audio


def _boom(message):
    def _raise(*_args):
        raise RuntimeError(message)
    return _raise


def _button(qtbot, *, audio, transcribe=None, rewrite=None, recorder=None, errors=None):
    holder = {"prompt": "a cat"}
    worker = VoiceWorker(
        transcribe or (lambda a: "make it a dog"),
        rewrite or (lambda cur, instr: cur + " dog"),
    )
    button = VoiceButton(
        lambda: holder["prompt"],
        lambda new: holder.__setitem__("prompt", new),
        recorder=recorder if recorder is not None else FakeRecorder(audio),
        worker=worker,
        on_error=(errors.append if errors is not None else None),
    )
    qtbot.addWidget(button)
    return button, holder


def test_hold_then_release_records_and_updates_the_prompt(qtbot):
    button, holder = _button(qtbot, audio=object())
    button._start()
    assert button._recorder.started
    button._stop()
    assert button._recorder.stopped
    assert holder["prompt"] == "a cat dog"


def test_release_with_no_audio_leaves_the_prompt_alone(qtbot):
    button, holder = _button(qtbot, audio=None, transcribe=_boom("should not transcribe"))
    button._start()
    button._stop()
    assert holder["prompt"] == "a cat"  # nothing captured, nothing changed


def test_a_rewrite_failure_is_routed_to_on_error(qtbot):
    errors = []
    button, holder = _button(qtbot, audio=object(), rewrite=_boom("no server"), errors=errors)
    button._start()
    button._stop()
    assert holder["prompt"] == "a cat"          # left unchanged
    assert errors and "no server" in errors[0]


def test_a_recorder_failure_is_reported(qtbot):
    errors = []

    class BrokenRecorder:
        def start(self):
            raise RuntimeError("no mic")

        def stop(self):
            return None

    button, _ = _button(qtbot, audio=None, recorder=BrokenRecorder(), errors=errors)
    button._start()
    assert errors and "no mic" in errors[0]
