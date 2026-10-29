"""Runs that land while Origenerator is closed, and how he hears about them.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from origenerator import landed_while_away
from origenerator.db import Database
from origenerator.output_places import OutputPlaces
from origenerator.single_instance import Copies
from origenerator.workflows import WORKFLOW_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[1]


def _in_flight(db, prompt_id="vid", workflow_name="wan22_i2v"):
    wf = WORKFLOW_REGISTRY[workflow_name]
    db.insert_generation(prompt_id=prompt_id, workflow_name=workflow_name,
                         workflow_version=wf.version, positive_prompt="it turns",
                         params_json=json.dumps(dict(wf.default_params())),
                         workflow_json="{}")
    db.update_generation(prompt_id, status="running")
    return db.get_generation(prompt_id)


def _landed(filename="vid.mp4", seconds=252):
    ms = int(seconds * 1000)
    return {
        "outputs": {"19": {"images": [{"filename": filename, "subfolder": "video"}]}},
        "status": {"messages": [["execution_start", {"timestamp": 1_000}],
                                ["execution_success", {"timestamp": 1_000 + ms}]]},
    }


class _Api:
    """ComfyUI's history, as the watcher asks after it."""

    def __init__(self, history):
        self._history = history
        self.asked = []

    def fetch_history(self, prompt_id):
        self.asked.append(prompt_id)
        return self._history.get(prompt_id, {})


def _watch(db, api, tmp_path, **over):
    said = []
    landed_while_away.watch(
        db, api,
        announce=said.append,
        app_is_running=over.pop("app_is_running", lambda: False),
        sleep=over.pop("sleep", lambda _seconds: None),
        places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs",
        **over)
    return said


def test_a_run_that_lands_while_the_app_is_closed_is_announced(tmp_path):
    # The app is what watches ComfyUI, so a run that lands after he closes it
    # was announced by nobody and sat in the gallery as still being made.
    db = Database(tmp_path / "t.db")
    _in_flight(db)

    said = _watch(db, _Api({"vid": _landed()}), tmp_path)

    assert [notice.title for notice in said] == ["Video ready"]
    assert db.get_generation("vid")["status"] == "completed"


def test_the_watcher_asks_nothing_once_the_app_is_back(tmp_path):
    # From then on the app is watching those runs itself, and two watchers would
    # announce every one of them twice.
    db = Database(tmp_path / "t.db")
    _in_flight(db)
    api = _Api({})

    said = _watch(db, api, tmp_path, app_is_running=lambda: True)

    assert said == []
    assert api.asked == []
    assert db.get_generation("vid")["status"] == "running"


def test_a_run_still_going_is_waited_out(tmp_path):
    # An empty history is "not yet": the run keeps its place and is asked after
    # again, and nothing is announced until it lands.
    db = Database(tmp_path / "t.db")
    _in_flight(db)
    landed = {}
    api = _Api(landed)
    naps = []

    def nap(seconds):
        naps.append(seconds)
        landed["vid"] = _landed()           # it lands while the watcher waits

    said = _watch(db, api, tmp_path, sleep=nap)

    assert naps          # it waited rather than asking once and giving up
    assert [notice.title for notice in said] == ["Video ready"]


def test_a_run_comfyui_ended_with_nothing_saved_is_not_written_down_as_finished(tmp_path):
    db = Database(tmp_path / "t.db")
    _in_flight(db)

    said = _watch(db, _Api({"vid": {"outputs": {}}}), tmp_path, patience_seconds=0)

    assert said == []
    assert db.get_generation("vid")["status"] == "running"


@pytest.mark.parametrize(("landed", "over", "said"), [
    ({"vid": _landed()}, {}, "every run"),
    ({}, {"app_is_running": lambda: True}, "Origenerator is open again"),
    ({}, {"patience_seconds": 0}, "gave up"),
], ids=["all-landed", "app-back", "gave-up"])
def test_the_watcher_says_in_the_log_how_it_stopped(tmp_path, caplog, landed, over, said):
    db = Database(tmp_path / "t.db")
    _in_flight(db)

    with caplog.at_level(logging.INFO, logger=landed_while_away.__name__):
        _watch(db, _Api(landed), tmp_path, **over)

    assert f"Stopped waiting: {said}" in caplog.text


def test_quitting_hands_the_runs_still_in_flight_to_a_process_of_its_own(tmp_path):
    db = Database(tmp_path / "t.db")
    _in_flight(db)
    started = []

    assert landed_while_away.hand_over_what_is_in_flight(
        db, "Origenerator.Preview", spawn=started.append) is True
    assert started == ["Origenerator.Preview"]


@pytest.fixture
def started(monkeypatch):
    """What the app asked Windows to start, each answered as process 4321."""
    asked = []

    def popen(args, **_named):
        asked.append(args)
        return SimpleNamespace(pid=4321)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return asked


def test_the_watcher_runs_on_an_interpreter_that_opens_no_console(tmp_path, started):
    # The app runs on the console interpreter its launcher's log needs. Started on
    # that one, the watcher's own interpreter was handed a console window, left
    # open on his desktop until the runs in flight landed.
    db = Database(tmp_path / "t.db")
    _in_flight(db)

    landed_while_away.hand_over_what_is_in_flight(db, "Origenerator")

    assert Path(started[0][0]).name == "pythonw.exe"


def test_the_log_names_the_process_left_waiting_on_the_runs(tmp_path, started, caplog):
    db = Database(tmp_path / "t.db")
    _in_flight(db)

    with caplog.at_level(logging.INFO, logger=landed_while_away.__name__):
        landed_while_away.hand_over_what_is_in_flight(db, "Origenerator")

    assert "4321" in caplog.text


def test_quitting_with_nothing_in_flight_starts_nothing(tmp_path):
    db = Database(tmp_path / "t.db")
    started = []

    assert landed_while_away.hand_over_what_is_in_flight(
        db, "Origenerator", spawn=started.append) is False
    assert started == []


def test_what_the_watcher_says_lands_in_the_apps_log(tmp_path):
    # Its process has no window and no console, so a line it logs anywhere else
    # is read by nobody.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p)
    subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path\n"
         "import origenerator.content as content\n"
         "content.LOCAL_CONTENT = content.EXAMPLE_CONTENT\n"
         "from origenerator import landed_while_away as watcher\n"
         f"watcher.LIBRARY_STATE_DIR = watcher.STATE_DIR = Path({str(tmp_path)!r})\n"
         "watcher.watch = lambda *_a, **_k: watcher.logger.info('said by the watcher')\n"
         "watcher.main(['Origenerator'])\n"],
        cwd=REPO_ROOT, env=env, check=True,
    )

    assert "said by the watcher" in (tmp_path / "origenerator.log").read_text(encoding="utf-8")


def test_the_watcher_asks_whether_a_copy_holds_the_library_it_waits_for(tmp_path, monkeypatch):
    monkeypatch.setattr(landed_while_away, "LIBRARY_STATE_DIR", tmp_path)
    monkeypatch.setattr(landed_while_away, "_log_into_the_apps_file", lambda: None)
    asked = {}
    monkeypatch.setattr(landed_while_away, "watch",
                        lambda db, api, *, announce, app_is_running: asked.update(
                            app_is_running=app_is_running))

    assert landed_while_away.main(["Origenerator"]) == 0

    claim = Copies(tmp_path).claim_the_library()
    try:
        assert asked["app_is_running"]()
    finally:
        claim.let_go()
    assert not asked["app_is_running"]()


def _training(tmp_path, monkeypatch, *, ends_with: dict, after_naps: int = 0):
    job = {"part": "hands", "display_name": "Hands fix 1.0",
           "status": str(tmp_path / "status.json")}
    trainer = SimpleNamespace(alive=after_naps > 0, began=1_000_000.0)
    trainer.running = lambda: trainer.alive
    monkeypatch.setattr(landed_while_away.lora_training, "trainer_of", lambda kept: trainer)
    naps = []

    def end():
        trainer.alive = False
        Path(job["status"]).write_text(json.dumps(ends_with), encoding="utf-8")
        os.utime(job["status"], (trainer.began + 2952, trainer.began + 2952))

    def nap(_seconds):
        naps.append(_seconds)
        if len(naps) >= after_naps:
            end()

    if not after_naps:
        end()
    return job, nap


def test_a_training_that_ends_while_the_app_is_closed_is_announced(tmp_path, monkeypatch):
    job, nap = _training(tmp_path, monkeypatch,
                         ends_with={"state": "done", "lora": "hands 2026-10-21 1500.safetensors"})

    said = _watch(Database(tmp_path / "t.db"), _Api({}), tmp_path, sleep=nap, trainings=[job])

    assert [(notice.title, notice.body) for notice in said] == [("LoRA ready", "Hands fix 1.0 · 49:12")]


def test_a_training_still_going_is_waited_out_and_its_failure_announced(tmp_path, monkeypatch):
    job, nap = _training(tmp_path, monkeypatch, after_naps=2,
                         ends_with={"state": "failed", "message": "Out of memory."})

    said = _watch(Database(tmp_path / "t.db"), _Api({}), tmp_path, sleep=nap, trainings=[job])

    assert [notice.title for notice in said] == ["Training failed"]


def test_quitting_while_a_training_runs_hands_it_to_a_process_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(landed_while_away.fix_training, "running_trainings",
                        lambda: [{"part": "hands"}])
    started = []

    assert landed_while_away.hand_over_what_is_in_flight(
        Database(tmp_path / "t.db"), "Origenerator", spawn=started.append) is True
    assert started == ["Origenerator"]
