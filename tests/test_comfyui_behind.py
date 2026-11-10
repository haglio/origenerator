from __future__ import annotations

import logging

from PyQt6.QtCore import QObject

from origenerator.boot_passes import Library
from origenerator.db import Database, NewGeneration
from origenerator.gui import job_queue
from origenerator.gui.comfyui_behind import DID_NOT_COME_UP, bring_comfyui_up_behind_the_window
from origenerator.inflight import in_flight_at
from origenerator.output_places import OutputPlaces

logger = logging.getLogger("tests.comfyui_behind")


class _ComfyUIThatRestarted:
    def fetch_queue(self):
        return set()

    def fetch_history(self, prompt_id):
        return {}


def _running(db, prompt_id):
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                                       workflow_version="v1", params_json="{}",
                                       workflow_json="{}"))
    db.update_generation(prompt_id, status="running")


def _a_launch_with_a_run_in_flight(tmp_path):
    db = Database(tmp_path / "test.db")
    _running(db, "from-before")
    library = Library(db=db, client=_ComfyUIThatRestarted(),
                      places=OutputPlaces.in_one_folder(tmp_path / "saves"),
                      thumb_dir=tmp_path / "thumbs", log_dir=tmp_path / "logs", inbox=None,
                      in_flight=in_flight_at(db))
    _running(db, "this-session")
    return db, library


def _statuses(db):
    return {row["prompt_id"]: row["status"] for row in db.list_generations()}


def test_once_comfyui_answers_the_runs_in_flight_at_launch_are_reconnected_and_no_other(
        qtbot, tmp_path, monkeypatch):
    db, library = _a_launch_with_a_run_in_flight(tmp_path)
    monkeypatch.setattr(job_queue, "BRING_UP_COMFYUI", lambda: True)
    owner = QObject()

    bring_comfyui_up_behind_the_window(library, logger, owner=owner, then=lambda: None)

    qtbot.waitUntil(lambda: "from-before" not in _statuses(db), timeout=5000)
    assert _statuses(db) == {"this-session": "running"}


def test_core_is_ready_once_comfyui_answered_and_the_runs_in_flight_were_reconnected(
        qtbot, tmp_path, monkeypatch):
    db, library = _a_launch_with_a_run_in_flight(tmp_path)
    monkeypatch.setattr(job_queue, "BRING_UP_COMFYUI", lambda: True)
    seen_when_ready = []

    bring_comfyui_up_behind_the_window(
        library, logger, owner=QObject(), then=lambda: seen_when_ready.append(_statuses(db)))

    qtbot.waitUntil(lambda: bool(seen_when_ready), timeout=5000)
    assert seen_when_ready == [{"this-session": "running"}]


def test_a_comfyui_that_never_comes_up_leaves_every_run_for_the_next_launch_and_says_so(
        qtbot, tmp_path, monkeypatch, caplog):
    db, library = _a_launch_with_a_run_in_flight(tmp_path)
    monkeypatch.setattr(job_queue, "BRING_UP_COMFYUI", lambda: False)
    ready = []

    with caplog.at_level(logging.WARNING, logger=logger.name):
        bring_comfyui_up_behind_the_window(library, logger, owner=QObject(),
                                           then=lambda: ready.append(True))
        qtbot.waitUntil(lambda: DID_NOT_COME_UP in caplog.messages, timeout=5000)

    assert _statuses(db) == {"from-before": "running", "this-session": "running"}
    assert ready == []


def test_a_copy_with_no_way_to_start_comfyui_says_so_at_once(tmp_path, monkeypatch, caplog):
    db, library = _a_launch_with_a_run_in_flight(tmp_path)
    monkeypatch.setattr(job_queue, "BRING_UP_COMFYUI", None)
    ready = []

    with caplog.at_level(logging.WARNING, logger=logger.name):
        bring_comfyui_up_behind_the_window(library, logger, owner=QObject(),
                                           then=lambda: ready.append(True))

    assert caplog.messages == [DID_NOT_COME_UP]
    assert _statuses(db) == {"from-before": "running", "this-session": "running"}
    assert ready == []
