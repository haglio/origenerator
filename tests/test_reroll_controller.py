"""RerollController — launching re-roll jobs: whole-folder, per-seed, and combine."""

import json
from unittest.mock import MagicMock

from origenerator import gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.reroll_controller import RerollController
from origenerator.workflows import WORKFLOW_REGISTRY

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]
_IMAGE_WF = "flux_t2i_upscaled"


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


def _image_row(prompt_id="img-1", filename="frame_001.png", seed=100):
    """A completed image generation whose output file an i2v can seed from."""
    image_wf = WORKFLOW_REGISTRY[_IMAGE_WF]
    return {
        "prompt_id": prompt_id,
        "workflow_name": _IMAGE_WF,
        "workflow_version": image_wf.version,
        "status": "completed",
        "source": "generated",
        "params_json": json.dumps({**image_wf.default_params(), "seed": seed}),
        "workflow_json": "{}",
        "output_files": json.dumps([{"filename": filename, "subfolder": "", "type": "output"}]),
    }


def _video_row(prompt_id="vid-1", input_image="frame_001.png [output]", noise_seed=11, seed=22):
    """A completed i2v whose start frame is ``_image_row``'s output."""
    return {
        "prompt_id": prompt_id,
        "workflow_name": "wan22_i2v",
        "status": "completed",
        "source": "generated",
        "params_json": json.dumps(_params(input_image=input_image, noise_seed=noise_seed, seed=seed)),
    }


def _launched_params(db, workflow_name):
    """The params_json (as a dict) of the launched row for ``workflow_name``."""
    row = next(r for r in db.list_generations() if r["workflow_name"] == workflow_name)
    return json.loads(row["params_json"])


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


# --- per-item seed re-rolls: keep one seed, re-roll the other ----------------

def test_reroll_video_seed_keeps_the_frame_and_rerolls_only_the_video_seed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)

    controller.reroll_video_seed("k", _video_row(noise_seed=11, seed=22))

    # One job — the video itself — with no image re-roll first.
    client.submit_job.assert_called_once()
    rows = db.list_generations()
    assert len(rows) == 1 and rows[0]["workflow_name"] == "wan22_i2v"
    params = _launched_params(db, "wan22_i2v")
    assert params["input_image"] == "frame_001.png [output]"        # same start frame
    assert params["noise_seed"] != 11 and params["seed"] != 22       # video seeds re-rolled


def test_reroll_image_seed_regenerates_the_frame_then_keeps_the_video_seed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    image = _image_row(seed=100)
    db.restore_generation(image)  # _reroll_source_image reads the full row from the DB

    controller.reroll_image_seed("k", _video_row(noise_seed=11, seed=22), [image])

    # The first launched job is the IMAGE workflow, its seed re-rolled.
    client.submit_job.assert_called_once()
    assert _launched_params(db, _IMAGE_WF)["seed"] != 100

    # Completing the image runs the video next — on the new frame, video seed kept.
    image_job = controller.job_for("k")
    image_job.finished.emit(
        [{"filename": "newframe.png", "subfolder": "", "type": "output"}], None, 1.0
    )
    assert client.submit_job.call_count == 2
    video_params = _launched_params(db, "wan22_i2v")
    assert video_params["input_image"] == "newframe.png [output]"     # fresh start frame
    assert video_params["noise_seed"] == 11 and video_params["seed"] == 22  # video seed kept


def test_reroll_image_seed_is_a_noop_when_the_frame_is_not_rebuildable(qtbot, tmp_path):
    # A hand-picked (un-rebuildable) frame can't be re-rolled; keeping the video
    # seed too would just duplicate the item, so nothing is launched.
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)

    controller.reroll_image_seed("k", _video_row(input_image="uploaded.png [input]"), [])

    client.submit_job.assert_not_called()
    assert not controller.has("k")


def test_start_rerolls_both_the_frame_and_the_video_seed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    image = _image_row(seed=100)
    db.restore_generation(image)  # _reroll_source_image reads the full row from the DB
    group = gallery.SettingsGroup("k", "settings", [_video_row(noise_seed=11, seed=22)])

    controller.start("k", group, [image])

    # A folder re-roll leads with the image (a new frame), its seed re-rolled.
    client.submit_job.assert_called_once()
    assert _launched_params(db, _IMAGE_WF)["seed"] != 100
    image_job = controller.job_for("k")
    image_job.finished.emit(
        [{"filename": "newframe.png", "subfolder": "", "type": "output"}], None, 1.0
    )
    video_params = _launched_params(db, "wan22_i2v")
    assert video_params["input_image"] == "newframe.png [output]"     # fresh frame
    assert video_params["noise_seed"] != 11 and video_params["seed"] != 22  # video seed re-rolled too
