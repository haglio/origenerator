from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from origenerator import config, fix_training
from origenerator.gui import fix_training_run
from origenerator.gui.fix_training_run import FixTrainingRun
from origenerator.gui.generation_job import JobState


class _Queue:
    def __init__(self, busy: bool):
        self.busy = busy
        self.held: list = []
        self.ended: list = []
        self.freed = 0

    def hold_for_training(self, training) -> None:
        self.held.append(training)
        training.ended.connect(self.ended.append)

    def making_something(self) -> bool:
        return self.busy

    def free_comfyui_memory(self) -> None:
        self.freed += 1


class _Trainer:
    def __init__(self):
        self.alive = True
        self.stopped = 0
        self.began = time.time() - 30

    def running(self) -> bool:
        return self.alive

    def stop(self) -> None:
        self.stopped += 1
        self.alive = False


def _run(qtbot, monkeypatch, tmp_path, *, busy=False):
    monkeypatch.setattr(fix_training_run, "POLL_MS", 5)
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    started: list[_Trainer] = []

    def start(job):
        started.append(_Trainer())
        return started[-1]

    monkeypatch.setattr(fix_training, "start", start)
    queue = _Queue(busy)
    job = {"part": "hands", "status": str(tmp_path / "status.json"),
           "log": str(tmp_path / "training.log")}
    run = FixTrainingRun(job, queue, reveal=lambda: None)
    return run, queue, started


def _say(tmp_path, **status) -> None:
    Path(tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")


def test_a_training_waits_for_what_comfyui_is_making_then_frees_it_and_starts(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path, busy=True)

    run.begin()
    qtbot.wait(30)
    assert queue.held == [run]
    assert started == []
    assert not run.running

    queue.busy = False
    qtbot.waitUntil(lambda: bool(started))
    assert queue.freed == 1
    assert run.running


def test_a_training_waiting_its_turn_reads_as_queued_with_nothing_to_count(
        qtbot, monkeypatch, tmp_path):
    run, _queue, _started = _run(qtbot, monkeypatch, tmp_path, busy=True)
    run.begin()

    assert run.reading().status == JobState.QUEUED
    assert run.reading().progress is None


def test_a_training_reads_how_far_its_cropping_and_then_its_steps_have_got(
        qtbot, monkeypatch, tmp_path):
    run, _queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))
    assert (run.reading().status, run.reading().stage) == (JobState.RUNNING, "Cropping photos")

    _say(tmp_path, state="cropping", done=2, total=8)
    qtbot.waitUntil(lambda: run.reading().pass_progress == (2, 8))
    assert run.reading().progress is None
    assert run.reading().started_at is not None

    _say(tmp_path, state="training", done=0, total=0)
    qtbot.waitUntil(lambda: run.reading().stage == "Training")
    assert run.reading().progress is None

    _say(tmp_path, state="training", done=30, total=2000)
    qtbot.waitUntil(lambda: run.reading().progress == (30, 2000))


def test_a_training_counts_down_from_how_long_the_last_ones_took(qtbot, monkeypatch, tmp_path):
    run, _queue, started = _run(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(fix_training, "typical_seconds", lambda: 2500.0)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    assert run.reading().typical_seconds == 2500.0


def test_a_finished_trainings_time_is_noted_where_its_lora_is_taken_not_by_the_run(
        qtbot, monkeypatch, tmp_path):
    noted = []
    run, _queue, started = _run(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(fix_training, "note_duration", noted.append)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.finished):
        _say(tmp_path, state="done", lora="hands 2026-10-21 1500.safetensors")
        started[0].alive = False

    assert noted == []


def test_a_finished_training_lets_the_queue_go_and_names_the_lora_it_made(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.finished) as made:
        _say(tmp_path, state="done", lora="hands 2026-10-19 0130.safetensors")
        started[0].alive = False

    assert made.args == [fix_training.lora_of({"lora": "hands 2026-10-19 0130.safetensors"})]
    (outcome,) = queue.ended
    assert (outcome.kind, outcome.display_name, outcome.ok) == ("Training", "Hands fix", True)
    assert outcome.seconds == pytest.approx(30, abs=10)
    assert not run.running


def test_a_failed_training_lets_the_queue_go_and_says_why(qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.failed) as stopped:
        _say(tmp_path, state="failed", message="The detector found nothing.")
        started[0].alive = False

    assert stopped.args == ["The detector found nothing."]
    (outcome,) = queue.ended
    assert (outcome.kind, outcome.ok) == ("Training", False)


def test_a_training_that_quits_without_a_word_says_so_and_where_its_log_is(
        qtbot, monkeypatch, tmp_path):
    run, _queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.failed) as stopped:
        started[0].alive = False

    assert "quit without saying why" in stopped.args[0]
    assert str(tmp_path / "training.log") in stopped.args[0]


def test_a_canceled_training_stops_its_program_lets_the_queue_go_and_says_nothing_more(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.canceled):
        run.cancel()

    assert started[0].stopped == 1
    assert queue.ended == [None]
    with qtbot.assertNotEmitted(run.failed), qtbot.assertNotEmitted(run.finished):
        qtbot.wait(30)


def test_a_training_canceled_while_it_waits_its_turn_starts_nothing(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path, busy=True)
    run.begin()

    with qtbot.waitSignal(run.canceled):
        run.cancel()
    queue.busy = False
    qtbot.wait(30)

    assert started == []
    assert queue.ended == [None]


def test_a_training_that_cannot_be_started_says_why_and_lets_the_queue_go(
        qtbot, monkeypatch, tmp_path):
    run, queue, _started = _run(qtbot, monkeypatch, tmp_path)

    def unstartable(job):
        raise FileNotFoundError("No usable Python interpreter found.")

    monkeypatch.setattr(fix_training, "start", unstartable)

    with qtbot.waitSignal(run.failed) as stopped:
        run.begin()

    assert "couldn't be started" in stopped.args[0]
    assert "No usable Python interpreter found." in stopped.args[0]
    assert [outcome.ok for outcome in queue.ended] == [False]


def test_a_training_left_running_by_an_earlier_launch_holds_the_line_at_once(
        qtbot, monkeypatch, tmp_path):
    run, queue, started = _run(qtbot, monkeypatch, tmp_path, busy=True)
    trainer = _Trainer()

    run.adopt(trainer)

    assert queue.held == [run]
    assert run.running
    assert started == []
    assert queue.freed == 0
    with qtbot.waitSignal(run.finished):
        _say(tmp_path, state="done", lora="hands 2026-10-21 1500.safetensors")
        trainer.alive = False
