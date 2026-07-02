"""RerollController.start_prepared — launch a job from already-built params."""

import json
from unittest.mock import MagicMock

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.reroll_controller import RerollController
from origenerator.workflows import WORKFLOW_REGISTRY

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]


def _client():
    client = ComfyUIClient()
    client.submit_job = MagicMock(return_value="comfy-X")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    return client


def _params(**over):
    params = dict(_I2V.default_params())
    params.update(over)
    return params


def test_start_prepared_launches_and_tracks_the_job(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)

    started = controller.start_prepared("video/wf/deadbeef", _I2V, _params(seed=3, noise_seed=9))

    assert started is True
    assert "video/wf/deadbeef" in controller.jobs
    client.submit_job.assert_called_once()
    rows = db.list_generations()
    assert len(rows) == 1 and rows[0]["status"] == "running"
    # The seed is reused verbatim — start_prepared does not randomize it.
    assert json.loads(rows[0]["params_json"])["seed"] == 3


def test_start_prepared_is_a_noop_when_the_folder_is_already_running(qtbot, tmp_path):
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)
    controller.start_prepared("k", _I2V, _params(seed=3))

    again = controller.start_prepared("k", _I2V, _params(seed=99))

    assert again is False
    client.submit_job.assert_called_once()  # not submitted a second time


def test_start_prepared_returns_false_without_a_client(qtbot, tmp_path):
    controller = RerollController(Database(tmp_path / "test.db"), client=None)

    assert controller.start_prepared("k", _I2V, _params()) is False
