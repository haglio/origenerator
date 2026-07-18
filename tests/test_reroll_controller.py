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


def test_finished_names_the_folder_and_the_generation(qtbot, tmp_path):
    # The signal carries the prompt_id alongside the folder key so the view can
    # tell whose completion this is — a user re-roll to load into the front tab,
    # or a background experiment to leave the tabs alone for.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("k", _I2V, _params())
    prompt_id = controller.job_for("k").prompt_id
    finished = []
    controller.finished.connect(lambda key, pid: finished.append((key, pid)))

    controller.job_for("k").finished.emit([{"filename": "out.mp4"}], None, 1.0)

    assert finished == [("k", prompt_id)]


def test_start_prepared_records_the_callers_source(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)

    controller.start_prepared("k", _I2V, _params(), source="experiment")

    assert db.list_generations()[0]["source"] == "experiment"


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


# --- combine's image re-roll: a fresh frame from the dropped image ------------

def test_start_reroll_from_image_regenerates_the_frame_then_runs_the_given_video(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    image = _image_row(seed=100)
    image_wf = WORKFLOW_REGISTRY[_IMAGE_WF]
    video_params = _params(input_image="frame_001.png [output]", noise_seed=11, seed=22)

    started = controller.start_reroll_from_image("k", image, image_wf, _I2V, video_params)

    # The dropped image is re-rolled first (its own seed fresh)...
    assert started is True
    client.submit_job.assert_called_once()
    assert _launched_params(db, _IMAGE_WF)["seed"] != 100
    # ...then the given video runs on the new frame, its seed used verbatim.
    image_job = controller.job_for("k")
    image_job.finished.emit(
        [{"filename": "newframe.png", "subfolder": "", "type": "output"}], None, 1.0
    )
    vparams = _launched_params(db, "wan22_i2v")
    assert vparams["input_image"] == "newframe.png [output]"
    assert vparams["noise_seed"] == 11 and vparams["seed"] == 22


def test_start_reroll_from_image_is_a_noop_when_the_folder_is_already_running(qtbot, tmp_path):
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)
    image_wf = WORKFLOW_REGISTRY[_IMAGE_WF]
    controller.start_reroll_from_image("k", _image_row(), image_wf, _I2V, _params())

    again = controller.start_reroll_from_image("k", _image_row(), image_wf, _I2V, _params())

    assert again is False
    client.submit_job.assert_called_once()


def test_progress_tick_persists_the_jobs_progress_to_its_row(qtbot, tmp_path):
    # A running job's live progress is written to its row, so a restart can resume
    # the bar where it was instead of spinning until ComfyUI's next per-step push.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    key = "video/wf/deadbeef"
    controller.start_prepared(key, _I2V, _params(steps=20, seed=3, noise_seed=9))
    job = controller.jobs[key]

    client.progress.emit(job.prompt_id, 5, 10)  # a live sampler step

    state = json.loads(db.get_generation(job.prompt_id)["progress_json"])
    assert state["last_progress"] == list(job.last_progress)


def test_progress_persistence_is_throttled(qtbot, tmp_path):
    # Ticks fire per step (sub-second for images); only the first of a burst is
    # written, so the disk isn't hammered — the value stays recent enough to resume.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    key = "video/wf/deadbeef"
    controller.start_prepared(key, _I2V, _params(steps=20))
    pid = controller.jobs[key].prompt_id

    client.progress.emit(pid, 5, 10)                       # first tick -> written
    first = db.get_generation(pid)["progress_json"]
    client.progress.emit(pid, 6, 10)                       # same second -> throttled
    assert db.get_generation(pid)["progress_json"] == first


def test_reconnect_running_seeds_progress_from_the_row(qtbot, tmp_path):
    # On restart the reconnected job comes back already showing its last position.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    db.insert_generation(prompt_id="rr", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="x", seed=1,
                         params_json=json.dumps({**wf.default_params(), "seed": 1}),
                         workflow_json="{}")
    db.update_generation("rr", status="running", progress_json=json.dumps(
        {"last_progress": [30, 50],
         "tracker": {"total": 50, "banked": 0, "stage_max": 50, "last_value": 30}}))

    controller.reconnect_running()

    job = next(j for j in controller.jobs.values() if j.prompt_id == "rr")
    assert job.last_progress == (30, 50)


def test_parse_progress_state_tolerates_absent_or_corrupt():
    from origenerator.gui.reroll_controller import _parse_progress_state
    assert _parse_progress_state(None) is None
    assert _parse_progress_state("") is None
    assert _parse_progress_state("not json") is None
    assert _parse_progress_state("[1, 2]") is None          # valid JSON, but not a dict
    assert _parse_progress_state('{"total": 20}') == {"total": 20}
