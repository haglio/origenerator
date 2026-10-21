from __future__ import annotations

import json
from pathlib import Path

from origenerator import fix_training
from origenerator.gui import fix_training_run
from origenerator.gui.fix_training_run import FixTrainingRun


class _Queue:
    def __init__(self, busy: bool):
        self.busy = busy
        self.held: list[bool] = []
        self.freed = 0

    def hold_for_training(self, held: bool) -> None:
        self.held.append(held)

    def making_something(self) -> bool:
        return self.busy

    def free_comfyui_memory(self) -> None:
        self.freed += 1


class _Step:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


def _run(qtbot, monkeypatch, tmp_path, *, busy=False):
    monkeypatch.setattr(fix_training_run, "POLL_MS", 5)
    started: list[tuple[str, _Step]] = []

    def start(job, step):
        started.append((step, _Step()))
        return started[-1][1]

    monkeypatch.setattr(fix_training, "start", start)
    queue = _Queue(busy)
    job = {"status": str(tmp_path / "status.json"), "log": str(tmp_path / "training.log")}
    run = FixTrainingRun(job, queue)
    return run, queue, started


def _say(tmp_path, **status) -> None:
    Path(tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")


def test_a_training_waits_for_what_comfyui_is_making_then_frees_it_and_crops(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path, busy=True)

    run.begin()
    qtbot.wait(30)
    assert queue.held == [True]
    assert started == []

    queue.busy = False
    qtbot.waitUntil(lambda: bool(started))
    assert queue.freed == 1
    assert [step for step, _process in started] == ["crop"]


def test_photos_cropped_without_a_hitch_are_trained_on_next(qtbot, monkeypatch, tmp_path):
    run, _queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    _say(tmp_path, state="cropping", done=3, total=3)
    started[0][1].code = 0

    qtbot.waitUntil(lambda: len(started) == 2)
    assert [step for step, _process in started] == ["crop", "train"]


def test_a_finished_training_lets_the_queue_go_and_names_the_lora_it_made(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.finished) as made:
        _say(tmp_path, state="done", lora="hands 2026-10-19 0130.safetensors")
        started[0][1].code = 0

    assert made.args == ["fixes\\hands 2026-10-19 0130.safetensors"]
    assert queue.held == [True, False]


def test_a_failed_training_lets_the_queue_go_and_says_why(qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.failed) as stopped:
        _say(tmp_path, state="failed", message="The detector found nothing.")
        started[0][1].code = 1

    assert stopped.args == ["The detector found nothing."]
    assert queue.held == [True, False]


def test_a_step_that_quits_without_a_word_says_so_and_where_its_log_is(
        qtbot, monkeypatch, tmp_path):
    run, _queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.failed) as stopped:
        started[0][1].code = 3221225786

    assert "quit without saying why" in stopped.args[0]
    assert str(tmp_path / "training.log") in stopped.args[0]


def test_a_step_that_cannot_be_started_says_why_and_lets_the_queue_go(
        qtbot, monkeypatch, tmp_path):
    run, queue, _started = _run(qtbot, monkeypatch, tmp_path)

    def unstartable(job, step):
        raise FileNotFoundError("No usable Python interpreter found.")

    monkeypatch.setattr(fix_training, "start", unstartable)

    with qtbot.waitSignal(run.failed) as stopped:
        run.begin()

    assert "couldn't be started" in stopped.args[0]
    assert "No usable Python interpreter found." in stopped.args[0]
    assert queue.held == [True, False]
