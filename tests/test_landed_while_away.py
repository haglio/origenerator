"""Runs that land while Origenerator is closed, and how he hears about them.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from origenerator import landed_while_away
from origenerator.db import Database
from origenerator.single_instance import Copies
from origenerator.workflows import WORKFLOW_REGISTRY


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
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
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


def test_quitting_hands_the_runs_still_in_flight_to_a_process_of_its_own(tmp_path):
    db = Database(tmp_path / "t.db")
    _in_flight(db)
    started = []

    assert landed_while_away.hand_over_what_is_in_flight(
        db, "Origenerator.Preview", spawn=started.append) is True
    assert started == ["Origenerator.Preview"]


def test_the_watcher_runs_on_an_interpreter_that_opens_no_console(tmp_path, monkeypatch):
    # The app runs on the console interpreter its launcher's log needs. Started on
    # that one, the watcher's own interpreter was handed a console window, left
    # open on his desktop until the runs in flight landed.
    db = Database(tmp_path / "t.db")
    _in_flight(db)
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **_named: started.append(args))

    landed_while_away.hand_over_what_is_in_flight(db, "Origenerator")

    assert Path(started[0][0]).name == "pythonw.exe"


def test_quitting_with_nothing_in_flight_starts_nothing(tmp_path):
    db = Database(tmp_path / "t.db")
    started = []

    assert landed_while_away.hand_over_what_is_in_flight(
        db, "Origenerator", spawn=started.append) is False
    assert started == []


def test_the_watcher_asks_whether_a_copy_holds_the_library_it_waits_for(tmp_path, monkeypatch):
    monkeypatch.setattr(landed_while_away, "LIBRARY_STATE_DIR", tmp_path)
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
