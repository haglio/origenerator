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


class _Trainer:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


def _run(qtbot, monkeypatch, tmp_path, *, busy=False):
    monkeypatch.setattr(fix_training_run, "POLL_MS", 5)
    trainer = _Trainer()
    started = []
    monkeypatch.setattr(fix_training, "start", lambda job: started.append(job) or trainer)
    queue = _Queue(busy)
    run = FixTrainingRun({"status": str(tmp_path / "status.json")}, queue)
    return run, queue, started, trainer


def _say(tmp_path, **status) -> None:
    Path(tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")


def test_a_training_waits_for_what_comfyui_is_making_then_frees_it_and_starts(
        qtbot, monkeypatch, tmp_path):
    run, queue, started, _trainer = _run(qtbot, monkeypatch, tmp_path, busy=True)

    run.begin()
    qtbot.wait(30)
    assert queue.held == [True]
    assert started == []

    queue.busy = False
    qtbot.waitUntil(lambda: bool(started))
    assert queue.freed == 1


def test_a_finished_training_lets_the_queue_go_and_names_the_lora_it_made(
        qtbot, monkeypatch, tmp_path):
    run, queue, started, trainer = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.finished) as made:
        _say(tmp_path, state="done", lora="hands 2026-10-19 0130.safetensors")
        trainer.code = 0

    assert made.args == ["fixes\\hands 2026-10-19 0130.safetensors"]
    assert queue.held == [True, False]


def test_a_failed_training_lets_the_queue_go_and_says_why(qtbot, monkeypatch, tmp_path):
    run, queue, started, trainer = _run(qtbot, monkeypatch, tmp_path)
    run.begin()
    qtbot.waitUntil(lambda: bool(started))

    with qtbot.waitSignal(run.failed) as stopped:
        _say(tmp_path, state="failed", message="The detector found nothing.")
        trainer.code = 1

    assert stopped.args == ["The detector found nothing."]
    assert queue.held == [True, False]
