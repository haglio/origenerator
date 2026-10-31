"""JobQueue — launching re-roll jobs: whole-folder, per-seed, and combine."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator import config, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.generation_state import GenerationSource
from origenerator.gui import job_queue as job_queue_module
from origenerator.gui.job_queue import COMFYUI_DID_NOT_START, JobQueue, _parse_progress_state
from origenerator.run_notice import RunOutcome
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.comfyui_folders import SUITE_FOLDERS
from tests.story_voices import voices_asked_for

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]
_IMAGE_WF = "flux_t2i_upscaled"


def _client():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-X")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    # Every send asks after an earlier run of its id first; answered here,
    # never by a server on the machine.
    client.fetch_history = MagicMock(return_value={})
    client.forget_history = MagicMock()
    client.executing_prompts = MagicMock(return_value=set())
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
    queue = JobQueue(db, client)

    started = queue.start_prepared("video/wf/deadbeef", _I2V, _params(seed=3, noise_seed=9))

    # The launched run names itself, so a caller can act on the row it just made.
    assert started == queue.jobs["video/wf/deadbeef"].prompt_id
    assert "video/wf/deadbeef" in queue.jobs
    client.submit_job.assert_called_once()
    rows = db.list_generations()
    assert len(rows) == 1 and rows[0]["status"] == "running"
    # The seed is reused verbatim — start_prepared does not randomize it.
    assert json.loads(rows[0]["params_json"])["seed"] == 3


def test_an_interrupted_job_lands_as_an_error_not_a_completion(qtbot, tmp_path):
    # A cancel from outside this job (ComfyUI's own UI, a second app instance)
    # ends the prompt the way a success ends it, with a history carrying no
    # outputs. The row must record the failure: a 'completed' row with no file is
    # invisible in the gallery yet still refuses a re-run of those settings as a
    # duplicate — the state the user hits as "it says it exists already".
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("video/wf/deadbeef", _I2V, _params(seed=3, noise_seed=9))
    prompt_id = queue.jobs["video/wf/deadbeef"].prompt_id

    client.job_completed.emit(prompt_id, {"outputs": {}})

    row = db.get_generation(prompt_id)
    assert row["status"] == "error"
    assert not json.loads(row["output_files"] or "[]")
    assert "video/wf/deadbeef" not in queue.jobs


def test_finished_names_the_folder_and_the_generation(qtbot, tmp_path):
    # The signal carries the prompt_id alongside the folder key so the view can
    # tell whose completion this is — a user re-roll to load into the front tab,
    # or a background experiment to leave the tabs alone for.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k", _I2V, _params())
    prompt_id = queue.job_for("k").prompt_id
    finished = []
    queue.finished.connect(lambda key, pid: finished.append((key, pid)))

    queue.job_for("k").finished.emit([{"filename": "out.mp4"}], None, 1.0)

    assert finished == [("k", prompt_id)]


def test_start_prepared_records_the_callers_source(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)

    queue.start_prepared("k", _I2V, _params(), source="experiment")

    assert db.list_generations()[0]["source"] == "experiment"


def test_a_second_user_launch_joins_a_folder_already_running(qtbot, tmp_path):
    # Two images of one folder's settings, both wanted: the second queues with the first
    # rather than being refused, which is what stopped them being made together.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    queue.start_prepared("k", _I2V, _params(seed=3))

    again = queue.start_prepared("k", _I2V, _params(seed=99))

    assert again
    assert len(queue.all_jobs) == 2
    # Both are queued; only the first has been handed to ComfyUI, which holds one
    # prompt of ours at a time -- a video asked for is "later".
    client.submit_job.assert_called_once()


def test_the_folders_live_tile_follows_the_folders_job_nearest_the_front(qtbot, tmp_path):
    # Things keyed by folder — the one live re-roll tile, the selection that
    # follows it — show the job being made or next to be, not whichever was
    # asked for first: an image asked for second takes the machine from the
    # first, and the tile has to follow it there.
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    first = _launch_image(queue, "k", seed=3)
    assert queue.job_for("k") is first
    second = _launch_image(queue, "k", seed=99)

    assert queue.job_for("k") is second
    assert queue.jobs == {"k": second}
    assert queue.queue_order == [second.prompt_id, first.prompt_id]
    assert queue.has("k") is True


def test_an_experiment_never_stacks_onto_a_busy_folder(qtbot, tmp_path):
    # Only work the user asked for may queue up; the background experimenter still
    # takes an idle folder or none at all.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    queue.start_prepared("k", _I2V, _params(seed=3))

    again = queue.start_prepared("k", _I2V, _params(seed=99), source="experiment")

    assert again is None
    client.submit_job.assert_called_once()


def test_a_generation_asked_for_with_no_server_never_starts(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), client=None)

    assert queue.start_prepared("k", _I2V, _params()) is None


# --- per-item seed re-rolls: keep one seed, re-roll the other ----------------

def test_reroll_video_seed_keeps_the_frame_and_rerolls_only_the_video_seed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)

    queue.reroll_video_seed("k", _video_row(noise_seed=11, seed=22))

    # One job — the video itself — with no image re-roll first.
    client.submit_job.assert_called_once()
    rows = db.list_generations()
    assert len(rows) == 1 and rows[0]["workflow_name"] == "wan22_i2v"
    params = _launched_params(db, "wan22_i2v")
    assert params["input_image"] == "frame_001.png [output]"        # same start frame
    assert params["noise_seed"] != 11                                # video seed re-rolled


def test_reroll_image_seed_regenerates_the_frame_then_keeps_the_video_seed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    image = _image_row(seed=100)
    db.restore_generation(image)  # _reroll_source_image reads the full row from the DB

    queue.reroll_image_seed("k", _video_row(noise_seed=11, seed=22), [image])

    # The first launched job is the IMAGE workflow, its seed re-rolled.
    client.submit_job.assert_called_once()
    assert _launched_params(db, _IMAGE_WF)["seed"] != 100

    # Completing the image runs the video next — on the new frame, video seed kept.
    image_job = queue.job_for("k")
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
    queue = JobQueue(Database(tmp_path / "test.db"), client)

    queue.reroll_image_seed("k", _video_row(input_image="uploaded.png [input]"), [])

    client.submit_job.assert_not_called()
    assert not queue.has("k")


def test_start_rerolls_both_the_frame_and_the_video_seed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    image = _image_row(seed=100)
    db.restore_generation(image)  # _reroll_source_image reads the full row from the DB
    group = gallery.SettingsGroup("k", "settings", [_video_row(noise_seed=11, seed=22)])

    queue.start_reroll("k", group, [image])

    # A folder re-roll leads with the image (a new frame), its seed re-rolled.
    client.submit_job.assert_called_once()
    assert _launched_params(db, _IMAGE_WF)["seed"] != 100
    image_job = queue.job_for("k")
    image_job.finished.emit(
        [{"filename": "newframe.png", "subfolder": "", "type": "output"}], None, 1.0
    )
    video_params = _launched_params(db, "wan22_i2v")
    assert video_params["input_image"] == "newframe.png [output]"     # fresh frame
    assert video_params["noise_seed"] != 11                             # video seed re-rolled too


def test_a_folder_reroll_launches_nothing_when_no_row_names_its_starting_image(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)

    queue.start_reroll("k", gallery.SettingsGroup("k", "settings", [_video_row(input_image="")]), [])

    client.submit_job.assert_not_called()
    assert not queue.has("k")


def test_a_second_chained_reroll_queues_behind_the_first(qtbot, tmp_path):
    # A chained image→video re-roll stacks like any other user launch now.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    image = _image_row()
    db.restore_generation(image)
    group = gallery.SettingsGroup("k", "settings", [_video_row()])
    queue.start_reroll("k", group, [image])

    queue.start_reroll("k", group, [image])

    assert len(queue.all_jobs) == 2
    client.submit_job.assert_called_once()  # the second waits its turn in the line


# --- user work preempts background experiments --------------------------------

def test_user_launch_preempts_a_running_experiment(qtbot, tmp_path):
    # A video experiment can hold the GPU for many minutes; a user's Generate must
    # kick it off rather than silently queue after it with a dead progress bar.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("exp-key", _I2V, _params(), source="experiment")
    experiment = queue.job_for("exp-key")
    client.progress.emit(experiment.prompt_id, "s", 1, 10)  # ComfyUI began executing it

    started = queue.start_prepared("user-key", _I2V, _params(seed=7))

    assert started
    client.interrupt.assert_called_once()              # the running experiment was stopped
    assert not queue.has("exp-key")
    assert db.get_generation(experiment.prompt_id) is None  # its abandoned row is dropped
    assert queue.has("user-key")


def test_user_launch_dequeues_a_still_queued_experiment_by_name(qtbot, tmp_path):
    # An experiment ComfyUI hasn't started yet is removed from its queue, and
    # stopped by name in case it has started meanwhile -- by name, so whatever
    # else is executing is untouched.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("exp-key", _I2V, _params(), source="experiment")
    experiment = queue.job_for("exp-key")

    queue.start_prepared("user-key", _I2V, _params(seed=7))

    client.cancel_prompt.assert_called_once_with(experiment.prompt_id)
    client.interrupt.assert_called_once_with(experiment.prompt_id)


def test_per_seed_rerolls_preempt_experiments_too(qtbot, tmp_path):
    # Every user path funnels through the same launch choke point, so a per-item
    # seed re-roll clears the experimenter exactly as the Generate button does.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("exp-key", _I2V, _params(), source="experiment")

    queue.reroll_video_seed("k", _video_row())

    assert not queue.has("exp-key")
    assert queue.has("k")


def test_an_experiment_launch_never_preempts(qtbot, tmp_path):
    # Only user work owns the GPU; a background experiment never bumps anything.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("exp-1", _I2V, _params(), source="experiment")

    queue.start_prepared("exp-2", _I2V, _params(seed=5), source="experiment")

    client.interrupt.assert_not_called()
    client.cancel_prompt.assert_not_called()
    assert queue.has("exp-1")


@pytest.mark.parametrize("source", ["base_render", "backfill"])
def test_other_work_nobody_asked_for_never_preempts_an_experiment_either(qtbot, tmp_path,
                                                                        source):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("exp-1", _I2V, _params(), source="experiment")

    queue.start_prepared("other", _I2V, _params(seed=5), source=source)

    client.interrupt.assert_not_called()
    client.cancel_prompt.assert_not_called()
    assert queue.has("exp-1")


def test_user_launch_claims_the_experiments_own_folder(qtbot, tmp_path):
    # Even when the user's settings land in the very folder the experiment runs
    # in, their Generate preempts it and takes the slot — not a silent no-op.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k", _I2V, _params(), source="experiment")

    started = queue.start_prepared("k", _I2V, _params(seed=7))

    assert started
    assert queue.job_for("k").source == "generated"
    assert client.submit_job.call_count == 2


def test_reconnected_experiments_stay_preemptible(qtbot, tmp_path):
    # Opening the app drops the batch the last absence queued, but one ComfyUI
    # refused to dequeue survives that sweep and is adopted as a live job. It
    # reconnects with its row's source, so the first user launch still clears it.
    client = _client()
    client.executing_prompts.return_value = {"exp-rr"}
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    db.insert_generation(prompt_id="exp-rr", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="x", seed=1,
                         params_json=json.dumps({**wf.default_params(), "seed": 1}),
                         workflow_json="{}", source="experiment")
    db.update_generation("exp-rr", status="running")
    queue.reconnect_running()

    queue.start_prepared("user-key", _I2V, _params(seed=7))

    client.interrupt.assert_called_once()  # stopped on the server, started or not
    assert db.get_generation("exp-rr") is None


def test_progress_tick_persists_the_jobs_progress_to_its_row(qtbot, tmp_path):
    # A running job's live progress is written to its row, so a restart can resume
    # the bar where it was instead of spinning until ComfyUI's next per-step push.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    key = "video/wf/deadbeef"
    queue.start_prepared(key, _I2V, _params(steps=20, seed=3, noise_seed=9))
    job = queue.jobs[key]

    client.progress.emit(job.prompt_id, "s", 5, 10)  # a live sampler step

    state = json.loads(db.get_generation(job.prompt_id)["progress_json"])
    assert state["last_progress"] == list(job.last_progress)


def test_progress_persistence_is_throttled(qtbot, tmp_path, monkeypatch):
    # Ticks fire per step (sub-second for images); only the first of a burst is
    # written, so the disk isn't hammered — the value stays recent enough to resume.
    # The interval is set here rather than waited out: a machine that stalls a
    # second between two emits would otherwise write the second one and fail.
    monkeypatch.setattr(job_queue_module, "_PROGRESS_PERSIST_INTERVAL_S", 3600)
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    key = "video/wf/deadbeef"
    queue.start_prepared(key, _I2V, _params(steps=20))
    pid = queue.jobs[key].prompt_id

    client.progress.emit(pid, "s", 5, 10)                       # first tick -> written
    first = db.get_generation(pid)["progress_json"]
    client.progress.emit(pid, "s", 6, 10)                       # inside the interval -> throttled
    assert db.get_generation(pid)["progress_json"] == first

    monkeypatch.setattr(job_queue_module, "_PROGRESS_PERSIST_INTERVAL_S", 0)
    client.progress.emit(pid, "s", 7, 10)                       # past it -> written again
    assert db.get_generation(pid)["progress_json"] != first


def test_reconnect_running_seeds_progress_from_the_row(qtbot, tmp_path):
    # On restart the reconnected job comes back already showing its last position.
    client = _client()
    client.executing_prompts.return_value = {"rr"}
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    db.insert_generation(prompt_id="rr", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="x", seed=1,
                         params_json=json.dumps({**wf.default_params(), "seed": 1}),
                         workflow_json="{}")
    db.update_generation("rr", status="running", progress_json=json.dumps(
        {"last_progress": [30, 50],
         "tracker": {"total": 50, "banked": 0, "stage_max": 50, "last_value": 30}}))

    queue.reconnect_running()

    job = next(j for j in queue.jobs.values() if j.prompt_id == "rr")
    assert job.last_progress == (30, 50)


# --- the line: what runs next, and what waits --------------------------------

def _image_params(**over):
    params = dict(WORKFLOW_REGISTRY[_IMAGE_WF].default_params())
    params.update(over)
    return params


def _launch_image(queue, key, **over):
    """Launch an image job — the kind that jumps the line — and return it."""
    queue.start_prepared(key, WORKFLOW_REGISTRY[_IMAGE_WF], _image_params(**over))
    return queue.newest_job_for(key)


def _launch_video(queue, key, **over):
    queue.start_prepared(key, _I2V, _params(**over))
    return queue.newest_job_for(key)


def test_queue_order_starts_out_empty(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    assert queue.queue_order == []


def test_comfyui_is_handed_one_job_at_a_time(qtbot, tmp_path):
    # The line is kept on this side of the wire precisely so it can still be
    # re-ordered: a prompt already on the server can only be interrupted.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)

    first = _launch_video(queue, "k1", seed=1)
    second = _launch_video(queue, "k2", seed=2)

    client.submit_job.assert_called_once()
    assert db.get_generation(first.prompt_id)["status"] == "running"
    assert db.get_generation(second.prompt_id)["status"] == "pending"
    assert queue.queue_order == [first.prompt_id, second.prompt_id]


def test_the_next_job_goes_the_moment_the_one_before_it_lands(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    first = _launch_video(queue, "k1", seed=1)
    second = _launch_video(queue, "k2", seed=2)

    first.finished.emit([{"filename": "out.mp4"}], None, 1.0)

    assert [call.args[1] for call in client.submit_job.call_args_list] == [
        first.prompt_id, second.prompt_id
    ]


def test_a_cancelled_job_starts_the_next_one_rather_than_stalling(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    first = _launch_video(queue, "k1", seed=1)
    second = _launch_video(queue, "k2", seed=2)

    queue.cancel_job(first.prompt_id)

    assert client.submit_job.call_args_list[-1].args[1] == second.prompt_id


def _frame_png() -> bytes:
    frame = BytesIO()
    Image.new("RGB", (40, 80), "red").save(frame, "PNG")
    return frame.getvalue()


def test_a_canceled_run_keeps_its_seeds_beside_the_last_frame_it_streamed(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    job = _launch_video(queue, "k1", noise_seed=11, audio_seed=33)
    client.preview_image.emit(job.prompt_id, _frame_png())

    queue.cancel_job(job.prompt_id)

    kept = db.list_seed_uses()
    assert {(r["kind"], r["seed_key"], r["seed"], r["media_type"]) for r in kept} == {
        ("canceled", "noise_seed", 11, "video"), ("canceled", "audio_seed", 33, "video")}
    assert all(Path(r["thumbnail_path"]).is_file() for r in kept)


def test_a_run_that_fails_keeps_its_seeds_too(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    job = _launch_video(queue, "k1", noise_seed=11, audio_seed=33)

    job.failed.emit("out of memory")

    assert {(r["kind"], r["seed"]) for r in db.list_seed_uses()} == {
        ("failed", 11), ("failed", 33)}


def test_an_experiment_stopped_for_the_person_keeps_no_seeds(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k1", _I2V, _params(noise_seed=11), source=GenerationSource.EXPERIMENT)

    queue.cancel_job(queue.newest_job_for("k1").prompt_id)

    assert db.list_seed_uses() == []


def test_a_submit_the_server_refuses_hands_over_the_next_one(qtbot, tmp_path):
    # A queue stalled on a job ComfyUI won't take would strand everything after
    # it; the refused job fails and the line carries on.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    client.submit_job = MagicMock(side_effect=[RuntimeError("bad prompt"), "ok"])

    _launch_video(queue, "k1", seed=1)           # refused, and dropped
    second = _launch_video(queue, "k2", seed=2)  # takes its place

    statuses = {row["prompt_id"]: row["status"] for row in db.list_generations()}
    assert statuses.pop(second.prompt_id) == "running"
    assert list(statuses.values()) == ["error"]


def test_background_work_the_server_refuses_is_recorded_but_not_announced(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    client.submit_job = MagicMock(side_effect=RuntimeError("bad prompt"))
    said = []
    queue.failed.connect(lambda key, message: said.append(key))

    queue.start_prepared("e1", WORKFLOW_REGISTRY[_IMAGE_WF], _image_params(),
                         source=GenerationSource.EXPERIMENT)

    assert said == []
    assert [row["status"] for row in db.list_generations()] == ["error"]


def _comfyui_down():
    return urllib.error.URLError(ConnectionRefusedError(
        10061, "No connection could be made because the target machine actively refused it"))


class _ComfyUIComingUp:
    """Bringing ComfyUI up, held until the test lets it finish."""

    def __init__(self, comes_up=True):
        self.comes_up = comes_up
        self.times = 0
        self.finish = threading.Event()

    def __call__(self):
        self.times += 1
        self.finish.wait(5)
        return self.comes_up


def test_a_press_while_comfyui_is_down_waits_as_queued_until_comfyui_answers(qtbot, tmp_path):
    client = _client()
    client.submit_job = MagicMock(side_effect=[_comfyui_down(), "comfy-X"])
    db = Database(tmp_path / "test.db")
    coming_up = _ComfyUIComingUp()
    queue = JobQueue(db, client, bring_up_comfyui=coming_up)
    said = []
    queue.failed.connect(lambda key, message: said.append(message))

    job = _launch_video(queue, "k1", seed=1)

    assert db.get_generation(job.prompt_id)["status"] == "pending"
    assert queue.queue_order == [job.prompt_id]
    coming_up.finish.set()
    qtbot.waitUntil(lambda: db.get_generation(job.prompt_id)["status"] == "running", timeout=5000)
    assert said == []


def test_everything_waiting_on_comfyui_fails_together_saying_origenerator_couldnt_start_it(
        qtbot, tmp_path):
    client = _client()
    client.submit_job = MagicMock(side_effect=_comfyui_down())
    db = Database(tmp_path / "test.db")
    coming_up = _ComfyUIComingUp(comes_up=False)
    queue = JobQueue(db, client, bring_up_comfyui=coming_up)
    said = []
    queue.failed.connect(lambda key, message: said.append((key, message)))
    first = _launch_video(queue, "k1", seed=1)
    second = _launch_video(queue, "k2", seed=2)

    coming_up.finish.set()
    qtbot.waitUntil(lambda: len(said) == 2, timeout=5000)

    assert said == [("k1", "Origenerator couldn't start ComfyUI."),
                    ("k2", "Origenerator couldn't start ComfyUI.")]
    rows = [db.get_generation(job.prompt_id) for job in (first, second)]
    assert [(row["status"], row["error_message"]) for row in rows] == [
        ("error", "Origenerator couldn't start ComfyUI.")] * 2
    assert queue.all_jobs == []
    assert (coming_up.times, client.submit_job.call_count) == (1, 1)


def test_a_bring_up_that_breaks_fails_what_waits_rather_than_holding_it_forever(qtbot, tmp_path):
    def no_comfyuiapp_here():
        raise FileNotFoundError("comfyui_server.py")

    client = _client()
    client.submit_job = MagicMock(side_effect=_comfyui_down())
    queue = JobQueue(Database(tmp_path / "test.db"), client, bring_up_comfyui=no_comfyuiapp_here)
    said = []
    queue.failed.connect(lambda key, message: said.append((key, message)))

    _launch_video(queue, "k1", seed=1)
    qtbot.waitUntil(lambda: bool(said), timeout=5000)

    assert said == [("k1", COMFYUI_DID_NOT_START)]


def _launch_story(queue, key, **over):
    return _launch_video(queue, key, scene_lines=["Come in."], **over)


def test_a_story_whose_lines_were_spoken_while_comfyui_went_down_waits_for_it_too(
        qtbot, tmp_path, monkeypatch):
    voices = voices_asked_for(monkeypatch)
    client = _client()
    db = Database(tmp_path / "test.db")
    coming_up = _ComfyUIComingUp()
    queue = JobQueue(db, client, bring_up_comfyui=coming_up)
    job = _launch_story(queue, "k1", seed=1)
    client.submit_job = MagicMock(side_effect=_comfyui_down())
    said = []
    queue.failed.connect(lambda key, message: said.append(message))

    voices[0].done()

    assert db.get_generation(job.prompt_id)["status"] == "pending"
    assert queue.queue_order == [job.prompt_id] and not queue.making_something()
    coming_up.finish.set()
    qtbot.waitUntil(lambda: len(voices) == 2, timeout=5000)
    assert said == []


def test_with_nothing_to_start_comfyui_a_story_it_never_heard_fails_like_any_refusal(
        qtbot, tmp_path, monkeypatch):
    voices = voices_asked_for(monkeypatch)
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    job = _launch_story(queue, "k1", seed=1)
    client.submit_job = MagicMock(side_effect=_comfyui_down())
    said = []
    queue.failed.connect(lambda key, message: said.append(message))

    voices[0].done()

    assert len(said) == 1 and "10061" in said[0]
    assert db.get_generation(job.prompt_id)["status"] == "error"


def test_a_storys_row_says_running_only_once_its_voice_is_done_and_comfyui_has_it(
        qtbot, tmp_path, monkeypatch):
    # A running row is one the next launch looks for on ComfyUI and clears when
    # ComfyUI never heard of it, which is how a story still speaking as the app
    # closed was lost.
    voices = voices_asked_for(monkeypatch)
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, _client())
    story = _launch_story(queue, "k1", seed=1)

    assert db.get_generation(story.prompt_id)["status"] == "pending"
    voices[0].done()
    assert db.get_generation(story.prompt_id)["status"] == "running"


def test_a_story_flushed_while_comfyui_makes_a_run_of_the_queues_waits_in_the_line(
        qtbot, tmp_path, monkeypatch):
    # Nobody is left to answer a voice once the line is flushed: the closing copy,
    # or the command that hands ComfyUI the backfill while the app is closed, ends
    # as the flush returns. A story whose voice was started there read as sent, and
    # never reached ComfyUI (2026-10-29, at every closing after that until found).
    voices = voices_asked_for(monkeypatch)
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, _client())
    _launch_video(queue, "k1", seed=1)
    story = _launch_story(queue, "k2", seed=2)

    queue.flush_to_server()

    assert voices == []
    assert db.get_generation(story.prompt_id)["status"] == "pending"


def test_a_story_a_closed_queue_hands_over_is_spoken_where_it_is_asked_then_sent(
        qtbot, tmp_path, monkeypatch):
    voices = voices_asked_for(monkeypatch)
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.close()
    story = _launch_story(queue, "k1", seed=1)

    queue.flush_to_server()

    assert [voice.how for voice in voices] == ["here"]
    assert [call.args[1] for call in client.submit_job.call_args_list] == [story.prompt_id]
    assert db.get_generation(story.prompt_id)["status"] == "running"


def test_a_closed_queue_leaves_its_line_to_the_flush_which_asks_a_silent_comfyui_once(
        qtbot, tmp_path):
    client = _client()
    client.submit_job = MagicMock(side_effect=[_comfyui_down(), _comfyui_down(),
                                               RuntimeError("asked again")])
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.close()
    waiting = _launch_video(queue, "k1", seed=1)

    assert queue.flush_to_server() == 0

    assert client.submit_job.call_count == 1
    assert db.get_generation(waiting.prompt_id)["status"] == "pending"


def test_a_queue_given_no_bring_up_brings_up_the_comfyui_this_machine_runs(
        qtbot, tmp_path, monkeypatch):
    brought_up = []
    monkeypatch.setattr(job_queue_module, "BRING_UP_COMFYUI", job_queue_module.bring_up_the_comfyui_here)
    monkeypatch.setattr(job_queue_module.comfyui_launcher, "bring_up",
                        lambda logger, host, port, comfyui_dir: brought_up.append(
                            (host, port, comfyui_dir)) or True)
    client = _client()
    client.submit_job = MagicMock(side_effect=[_comfyui_down(), "comfy-X"])
    queue = JobQueue(Database(tmp_path / "test.db"), client)

    _launch_video(queue, "k1", seed=1)
    qtbot.waitUntil(lambda: client.submit_job.call_count == 2, timeout=5000)

    assert brought_up == [(config.COMFYUI_HOST, config.COMFYUI_PORT, config.COMFYUI_DIR)]


class _UnbuildableWorkflow:
    def build_api_payload(self, params):
        raise KeyError("width")


def test_a_run_that_cannot_even_be_built_is_reported_as_failed(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    said = []
    queue.failed.connect(lambda key, message: said.append((key, message)))

    assert queue.start_prepared("k1", _UnbuildableWorkflow(), {}) is None

    (key, message), = said
    assert key == "k1"
    assert "width" in message


def test_a_folder_rerolls_start_frame_queues_behind_the_images_waiting(qtbot, tmp_path):
    # A chained i2v draws its start frame first, but a video is what was asked
    # for: placed as the image that prompt makes, it would take the front of the
    # line and put minutes of GPU ahead of every image already queued.
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, _client())
    image = _image_row(seed=100)
    db.restore_generation(image)  # _reroll_source_image reads the full row from the DB
    first = _launch_image(queue, "i0")
    second = _launch_image(queue, "i1")  # takes the machine; the first waits

    queue.start_reroll("k", gallery.SettingsGroup("k", "settings", [_video_row()]), [image])

    frame = queue.newest_job_for("k")
    assert queue.queue_order == [second.prompt_id, first.prompt_id, frame.prompt_id]


def test_a_background_experiment_never_jumps_the_line_whatever_it_makes(qtbot, tmp_path):
    # There can be a great many of them, and putting one in front of the user's
    # own work would be the whole cost of the feature.
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    _launch_video(queue, "v1", seed=1)   # on the server
    user_video = _launch_video(queue, "v2", seed=2)
    queue.start_prepared("e1", WORKFLOW_REGISTRY[_IMAGE_WF], _image_params(),
                              source="experiment")

    assert queue.queue_order[1] == user_video.prompt_id


# --- handing the line over as the app closes ---------------------------------

class _Training(QObject):
    ended = pyqtSignal(object)

    def __init__(self, running=True, holds_the_line=True):
        super().__init__()
        self.running = running
        self.holds_the_line = holds_the_line


def test_a_queue_held_for_a_training_hands_comfyui_nothing_until_it_ends(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    training = _Training()
    queue.watch_training(training)

    held = _launch_video(queue, "v1", seed=1)
    assert client.submit_job.call_count == 0
    assert not queue.making_something()
    assert queue.training is training

    training.ended.emit(None)
    assert [call.args[1] for call in client.submit_job.call_args_list] == [held.prompt_id]
    assert queue.making_something()
    assert queue.training is None


def test_a_queue_watching_a_training_that_yields_the_tile_hands_comfyui_its_jobs_as_ever(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    training = _Training(holds_the_line=False)
    queue.watch_training(training)

    sent = _launch_video(queue, "v1", seed=1)

    assert [call.args[1] for call in client.submit_job.call_args_list] == [sent.prompt_id]
    assert queue.training is training
    assert not queue.training_holds_the_machine()
    assert queue.flush_to_server() == 0


def test_a_training_that_ends_says_what_it_came_to_the_way_a_run_does(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    training = _Training()
    queue.watch_training(training)
    outcome = RunOutcome(kind="Training", display_name="Hands fix", seconds=2952.0, ok=True,
                         source="", generation="")

    with qtbot.waitSignal(queue.run_ended) as said:
        training.ended.emit(outcome)

    assert said.args == [outcome]


def test_a_canceled_training_says_nothing_of_what_it_came_to(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    training = _Training()
    queue.watch_training(training)

    with qtbot.assertNotEmitted(queue.run_ended):
        training.ended.emit(None)


def test_flush_hands_comfyui_everything_still_waiting(qtbot, tmp_path):
    # There is about to be nobody watching, so every reason to keep the line on
    # this side is gone and the server can work through the rest alone.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    being_made = _launch_video(queue, "v1", seed=1)
    second = _launch_video(queue, "v2", seed=2)
    third = _launch_video(queue, "v3", seed=3)

    assert queue.flush_to_server() == 2
    assert [call.args[1] for call in client.submit_job.call_args_list] == [
        being_made.prompt_id, second.prompt_id, third.prompt_id
    ]
    assert db.get_generation(third.prompt_id)["status"] == "running"


def test_closing_while_a_training_runs_leaves_the_line_for_the_next_launch(qtbot, tmp_path):
    # A training outlives the app, and anything ComfyUI is handed now would
    # fight it for the graphics card until one of the two ran out of memory.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.watch_training(_Training(running=True))
    waiting = _launch_video(queue, "v1", seed=1)

    assert queue.flush_to_server() == 0
    client.submit_job.assert_not_called()
    assert db.get_generation(waiting.prompt_id)["status"] == "pending"


def test_closing_while_a_training_waits_its_turn_hands_the_line_over_as_ever(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    queue.watch_training(_Training(running=False))
    waiting = _launch_video(queue, "v1", seed=1)

    assert queue.flush_to_server() == 1
    assert [call.args[1] for call in client.submit_job.call_args_list] == [waiting.prompt_id]


def test_a_submit_refused_as_the_app_closes_waits_for_the_next_copy_to_send_it(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    _launch_video(queue, "v1", seed=1)
    waiting = _launch_video(queue, "v2", seed=2)
    client.submit_job = MagicMock(side_effect=RuntimeError("bad prompt"))
    said = []
    queue.failed.connect(lambda key, message: said.append(key))

    assert queue.flush_to_server() == 0

    assert said == []
    next_copy = JobQueue(db, _client())
    next_copy.reconnect_running()
    assert next_copy.queue_order[-1] == waiting.prompt_id


def test_background_work_refused_as_the_app_closes_is_recorded_not_left_for_the_next_launch(
        qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    _launch_video(queue, "v1", seed=1)
    queue.start_prepared("e1", WORKFLOW_REGISTRY[_IMAGE_WF], _image_params(),
                         source=GenerationSource.EXPERIMENT)
    client.submit_job = MagicMock(side_effect=RuntimeError("bad prompt"))

    queue.flush_to_server()

    assert [row["status"] for row in db.list_generations()
            if row["source"] == GenerationSource.EXPERIMENT] == ["error"]


def test_what_waits_when_comfyui_does_not_answer_as_the_app_closes_stays_for_the_next_launch(
        qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    _launch_video(queue, "v1", seed=1)
    second = _launch_video(queue, "v2", seed=2)
    third = _launch_video(queue, "v3", seed=3)
    client.submit_job = MagicMock(side_effect=_comfyui_down())
    said = []
    queue.failed.connect(lambda key, message: said.append(key))

    assert queue.flush_to_server() == 0
    assert said == []
    assert [db.get_generation(job.prompt_id)["status"] for job in (second, third)] == [
        "pending", "pending"]
    client.submit_job.assert_called_once()


def test_flush_with_nothing_waiting_is_harmless(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)

    assert queue.flush_to_server() == 0
    client.submit_job.assert_not_called()


# --- taking a held queue back after a restart --------------------------------

def _pending_row(db, prompt_id, workflow_name="wan22_i2v", params=None):
    """A row the queue was still holding when the app closed."""
    workflow = WORKFLOW_REGISTRY.get(workflow_name)
    if params is None:
        params = dict(workflow.default_params()) if workflow is not None else {}
    db.insert_generation(prompt_id=prompt_id, workflow_name=workflow_name,
                         workflow_version="v", positive_prompt="x", seed=1,
                         params_json=json.dumps(params), workflow_json="{}")


def test_a_queue_held_when_the_app_closed_comes_back_as_a_queue(qtbot, tmp_path):
    # A pending row was never submitted, so there is nothing on the server to
    # rebind to — it rejoins the line under its own prompt id and waits its turn.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    _pending_row(db, "held-1")
    _pending_row(db, "held-2")

    queue.reconnect_running()

    assert [call.args[1] for call in client.submit_job.call_args_list] == ["held-1"]
    assert queue.queue_order == ["held-1", "held-2"]  # oldest first, as asked


def test_a_re_adopted_queue_starts_moving_again_at_once(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    _pending_row(db, "held-1")

    queue.reconnect_running()

    client.submit_job.assert_called_once()
    assert db.get_generation("held-1")["status"] == "running"


def test_a_held_row_whose_workflow_is_gone_is_dropped(qtbot, tmp_path):
    # It could never be sent, and left in flight it would sit in the queue forever.
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, _client())
    _pending_row(db, "orphan", workflow_name="a_workflow_that_left", params={})

    queue.reconnect_running()

    assert db.get_generation("orphan") is None
    assert queue.queue_order == []


# --- moving a job by hand -----------------------------------------------------

def test_a_job_moved_in_the_waiting_line_costs_nothing(qtbot, tmp_path):
    # A waiting job has never been sent, so its place is ours to change: no
    # dequeue, no re-submit, nothing the server has to agree to.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    head = _launch_video(queue, "k0", seed=0)
    second = _launch_video(queue, "k1", seed=1)
    third = _launch_video(queue, "k2", seed=2)
    client.submit_job.reset_mock()

    queue.move(third.prompt_id, before=second.prompt_id)

    assert queue.queue_order == [head.prompt_id, third.prompt_id, second.prompt_id]
    client.submit_job.assert_not_called()
    client.cancel_prompt.assert_not_called()


def test_a_job_moved_to_the_top_takes_the_machine_from_the_one_being_made(qtbot, tmp_path):
    # The user's own words for a move to the top: it deposes the job being
    # rendered, which goes back in the line right behind it and starts over.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    rendering = _launch_video(queue, "k0", seed=0)
    _rendering(client, rendering)
    waiting = _launch_video(queue, "k1", seed=1)

    queue.move(waiting.prompt_id, before=rendering.prompt_id)

    client.interrupt.assert_called_once_with(rendering.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == waiting.prompt_id
    assert queue.queue_order == [waiting.prompt_id, rendering.prompt_id]
    assert db.get_generation(rendering.prompt_id)["status"] == "pending"


def test_a_job_moved_to_the_top_waits_behind_a_shielded_one_being_made(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "k0", seed=0)
    _rendering(client, rendering)
    queue.shield(rendering.prompt_id, True)
    second = _launch_video(queue, "k1", seed=1)
    third = _launch_video(queue, "k2", seed=2)

    queue.move(third.prompt_id, before=rendering.prompt_id)

    client.interrupt.assert_not_called()
    assert queue.queue_order == [rendering.prompt_id, third.prompt_id, second.prompt_id]


def test_a_shielded_job_being_made_cannot_be_moved_down(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "k0", seed=0)
    _rendering(client, rendering)
    queue.shield(rendering.prompt_id, True)
    waiting = _launch_video(queue, "k1", seed=1)

    queue.move(rendering.prompt_id, before=None)

    client.interrupt.assert_not_called()
    assert queue.queue_order == [rendering.prompt_id, waiting.prompt_id]


def test_a_video_moved_to_the_top_starts_at_once_however_lately_an_image_was_asked_for(
        qtbot, tmp_path):
    # Its minute's wait is for a video nobody moved: one moved to the top took the
    # machine to be made now, and waiting would leave the machine idle.
    client = _client()
    now = [1000.0]
    queue = JobQueue(Database(tmp_path / "test.db"), client, clock=lambda: now[0])
    image = _launch_image(queue, "i", seed=1)
    _rendering(client, image)
    video = _launch_video(queue, "v", seed=2)

    queue.move(video.prompt_id, before=image.prompt_id)

    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id


def test_a_move_cannot_put_anything_ahead_of_a_job_put_first(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    waiting = _launch_image(queue, "i1", seed=1)
    rendering = _launch_image(queue, "i2", seed=2)
    queue.put_first({waiting.prompt_id, rendering.prompt_id})
    newer = _launch_image(queue, "i3", seed=3)

    queue.move(newer.prompt_id, before=rendering.prompt_id)

    assert queue.queue_order == [rendering.prompt_id, waiting.prompt_id, newer.prompt_id]


def test_a_job_let_go_over_one_the_line_does_not_hold_goes_to_its_end(qtbot, tmp_path):
    # Another app's prompts share the server, and a row can outlive its job by a
    # poll; neither is a place in this line.
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    head = _launch_video(queue, "k0", seed=0)
    second = _launch_video(queue, "k1", seed=1)
    third = _launch_video(queue, "k2", seed=2)

    queue.move(second.prompt_id, before="some-other-apps-prompt")

    assert queue.queue_order == [head.prompt_id, third.prompt_id, second.prompt_id]


def test_moving_a_job_the_line_does_not_hold_changes_nothing(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    head = _launch_video(queue, "k0", seed=0)
    second = _launch_video(queue, "k1", seed=1)

    queue.move("some-other-apps-prompt", before=head.prompt_id)

    assert queue.queue_order == [head.prompt_id, second.prompt_id]


def test_a_move_without_a_client_is_harmless(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), None)
    queue.move("anything", before=None)  # nothing to move, nothing to raise


def test_a_move_says_the_line_was_reordered_and_one_that_changes_nothing_says_nothing(
        qtbot, tmp_path):
    # The Job Queue redraws on that word, rather than a poll later: a row that
    # sits still after its button was pressed reads as a press that missed.
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    head = _launch_video(queue, "k0", seed=0)
    second = _launch_video(queue, "k1", seed=1)
    said = []
    queue.reordered.connect(lambda: said.append(queue.queue_order))

    queue.move_up(head.prompt_id)
    queue.move_down(head.prompt_id)

    assert said == [[second.prompt_id, head.prompt_id]]


def test_up_moves_a_job_ahead_of_the_one_above_it(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    head = _launch_video(queue, "k0", seed=0)
    second = _launch_video(queue, "k1", seed=1)
    third = _launch_video(queue, "k2", seed=2)

    queue.move_up(third.prompt_id)

    assert queue.queue_order == [head.prompt_id, third.prompt_id, second.prompt_id]


def test_up_on_a_video_just_behind_its_images_enhancement_takes_both_up(qtbot, tmp_path):
    # It cannot pass the enhancement it is made from, so the press is spent on
    # the job above that, and the enhancement goes up with it.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "r", seed=1)
    _rendering(client, rendering)
    queue.shield(rendering.prompt_id, True)
    enhance = _launch_enhance(queue, "e")
    other = _launch_video(queue, "o", seed=2)
    video = _launch_video(queue, "v", input_image=_IMAGE)
    queue.move(other.prompt_id, before=enhance.prompt_id)

    queue.move_up(video.prompt_id)

    assert queue.queue_order == [rendering.prompt_id, enhance.prompt_id, video.prompt_id,
                                 other.prompt_id]


def test_down_moves_a_job_behind_the_one_below_it(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    head = _launch_video(queue, "k0", seed=0)
    second = _launch_video(queue, "k1", seed=1)
    third = _launch_video(queue, "k2", seed=2)

    queue.move_down(second.prompt_id)

    assert queue.queue_order == [head.prompt_id, third.prompt_id, second.prompt_id]


def test_down_on_an_enhancement_just_ahead_of_its_video_takes_both_down(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "r", seed=1)
    _rendering(client, rendering)
    queue.shield(rendering.prompt_id, True)
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)
    other = _launch_video(queue, "o", seed=2)

    queue.move_down(enhance.prompt_id)

    assert queue.queue_order == [rendering.prompt_id, other.prompt_id, enhance.prompt_id,
                                 video.prompt_id]


def test_down_on_the_job_being_made_hands_the_machine_to_the_one_behind_it(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "k0", seed=0)
    _rendering(client, rendering)
    second = _launch_video(queue, "k1", seed=1)
    third = _launch_video(queue, "k2", seed=2)

    queue.move_down(rendering.prompt_id)

    client.interrupt.assert_called_once_with(rendering.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == second.prompt_id
    assert queue.queue_order == [second.prompt_id, rendering.prompt_id, third.prompt_id]


def test_the_top_of_the_line_cannot_go_up_nor_its_end_down(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "k0", seed=0)
    _rendering(client, rendering)
    middle = _launch_video(queue, "k1", seed=1)
    last = _launch_video(queue, "k2", seed=2)

    assert [(queue.can_move_up(job.prompt_id), queue.can_move_down(job.prompt_id))
            for job in (rendering, middle, last)] == [(False, True), (True, True), (True, False)]


def test_a_shielded_job_being_made_neither_moves_nor_lets_anything_up_past_it(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "k0", seed=0)
    _rendering(client, rendering)
    queue.shield(rendering.prompt_id, True)
    behind = _launch_video(queue, "k1", seed=1)
    last = _launch_video(queue, "k2", seed=2)

    assert [(queue.can_move_up(job.prompt_id), queue.can_move_down(job.prompt_id))
            for job in (rendering, behind, last)] == [(False, False), (False, True),
                                                      (True, False)]


def test_parse_progress_state_tolerates_absent_or_corrupt():
    assert _parse_progress_state(None) is None
    assert _parse_progress_state("") is None
    assert _parse_progress_state("not json") is None
    assert _parse_progress_state("[1, 2]") is None          # valid JSON, but not a dict
    assert _parse_progress_state('{"total": 20}') == {"total": 20}


# --- a submit the server is slow to answer -----------------------------------------

def _gated_client():
    """A client whose submit waits until the test lets it go: ComfyUI taking its
    time to answer, as it can for a minute. The wait is capped so a hand-over
    that never pumps the gate's opener fails instead of hanging the suite."""
    client = _client()
    gate = threading.Event()
    client.submit_job = MagicMock(side_effect=lambda payload, pid: gate.wait(5) and "comfy-X")
    return client, gate


def test_the_window_stays_alive_while_comfyui_takes_its_time_to_answer(qtbot, tmp_path):
    # ComfyUI can take a minute to accept a prompt (fifty seconds, 2026-09-05),
    # and the submit used to wait for it on the GUI thread: the window froze
    # solid, which reads as a crash, and the row the launch had just written
    # could not even be painted. The wait is off that thread now and the window
    # is kept alive meanwhile -- so a timer fires during it, and finds the
    # launch already in the line, on a row already written and announced.
    client, gate = _gated_client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    announced = []
    queue.changed.connect(lambda: announced.append(True))
    seen = {}

    def while_the_submit_is_out():
        seen["rows"] = [r["status"] for r in db.list_generations()]
        seen["in_line"] = queue.has("video/wf/deadbeef")
        seen["announced"] = len(announced)
        gate.set()

    QTimer.singleShot(0, while_the_submit_is_out)
    queue.start_prepared("video/wf/deadbeef", _I2V, _params())

    assert seen == {"rows": ["pending"], "in_line": True, "announced": 1}
    assert db.list_generations()[0]["status"] == "running"


def test_a_launch_canceled_while_its_submit_is_out_is_dequeued_when_it_lands(qtbot, tmp_path):
    # The window being alive, its Cancel can be pressed while the server has not
    # answered. The job is forgotten at once; when the server does take it, it is
    # told to let it go, since nobody wants it any more.
    client, gate = _gated_client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    seen = {}

    def while_the_submit_is_out():
        seen["pid"] = queue.jobs["video/wf/deadbeef"].prompt_id
        queue.cancel_job(seen["pid"])
        gate.set()

    QTimer.singleShot(0, while_the_submit_is_out)
    queue.start_prepared("video/wf/deadbeef", _I2V, _params())

    assert not queue.has("video/wf/deadbeef")
    assert queue.queue_order == []
    client.cancel_prompt.assert_called_once_with(seen["pid"])
    assert db.list_generations() == []


def test_a_launch_made_while_another_submit_is_out_waits_its_turn(qtbot, tmp_path):
    # One hand-over at a time, still: a second launch during the wait joins the
    # line rather than racing the first to the server.
    client, gate = _gated_client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    seen = {}

    def while_the_submit_is_out():
        queue.start_prepared("video/wf/second", _I2V, _params(seed=2))
        seen["submits"] = client.submit_job.call_count
        gate.set()

    QTimer.singleShot(0, while_the_submit_is_out)
    queue.start_prepared("video/wf/first", _I2V, _params(seed=1))

    first = queue.jobs["video/wf/first"].prompt_id
    second = queue.jobs["video/wf/second"].prompt_id
    assert seen["submits"] == 1
    assert queue.queue_order == [first, second]
    assert client.submit_job.call_count == 1  # the second waits for the first to finish


def test_a_finished_run_says_what_it_came_to(qtbot, tmp_path):
    # What the window's own surfaces can't carry: the run is over, so there is no
    # tile left to write on, and whoever tells the user needs the whole of it in
    # one record (see origenerator.run_notice).
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k", _I2V, _params())
    ended = []
    queue.run_ended.connect(ended.append)

    made = queue.job_for("k").prompt_id

    queue.job_for("k").finished.emit([{"filename": "out.mp4"}], None, 252.0)

    assert ended == [RunOutcome(kind="Video", display_name=_I2V.display_name, seconds=252.0,
                                ok=True, source=GenerationSource.GENERATED,
                                generation=made)]


def test_an_enhance_reports_the_image_it_improved_rather_than_itself(qtbot, tmp_path):
    # An enhance is an upgrade of an image already in the gallery: its own row is
    # folded into that image and deleted the moment it lands, so a notice
    # pointing at the run's own id would point at nothing by the time it is read.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k", _I2V, _params())
    job = queue.job_for("k")
    db.set_enhance_target(job.prompt_id, "the-image-it-improved")
    ended = []
    queue.run_ended.connect(ended.append)

    job.finished.emit([{"filename": "out.png"}], None, 252.0)

    assert ended[0].generation == "the-image-it-improved"


def test_a_failed_run_is_timed_by_the_clock_it_ran_under(qtbot, tmp_path):
    # A prompt that died wrote no execution_success for ComfyUI to measure to, so
    # the only measure left is the one the bar was counting up: how long since the
    # run began. Stamped here rather than waited out.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k", _I2V, _params())
    job = queue.job_for("k")
    job._started_at = time.time() - 200
    ended = []
    queue.run_ended.connect(ended.append)

    job.failed.emit("the sampler ran out of memory")

    assert not ended[0].ok
    assert 190 <= ended[0].seconds <= 210


def test_a_background_experiment_reports_itself_as_one(qtbot, tmp_path):
    # Whoever tells the user has to be able to leave the app's own idle work out:
    # a night of experiments is a night of interruptions otherwise.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    queue.start_prepared("k", _I2V, _params(), source=GenerationSource.EXPERIMENT)
    ended = []
    queue.run_ended.connect(ended.append)

    queue.job_for("k").finished.emit([{"filename": "out.mp4"}], None, 252.0)

    assert ended[0].source == GenerationSource.EXPERIMENT


# --- the user's image work takes the machine from a video being rendered -----

def _rendering(client, job):
    """ComfyUI has begun rendering ``job``."""
    client.progress.emit(job.prompt_id, "s", 1, 10)


def test_an_image_takes_the_machine_from_a_video_being_rendered(qtbot, tmp_path):
    # Minutes of GPU, most of it spent, against seconds the user is waiting for:
    # the video is stopped, the image goes at once, and the video starts over
    # after it -- ahead of the video queued after it, which it was in front of.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    rendering = _launch_video(queue, "v1", seed=1)
    waiting = _launch_video(queue, "v2", seed=2)
    _rendering(client, rendering)

    image = _launch_image(queue, "i")

    client.interrupt.assert_called_once_with(rendering.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == image.prompt_id
    assert queue.queue_order == [image.prompt_id, rendering.prompt_id, waiting.prompt_id]
    assert db.get_generation(image.prompt_id)["status"] == "running"
    assert db.get_generation(rendering.prompt_id)["status"] == "pending"


def test_the_video_set_aside_starts_over_a_minute_after_the_image_was_asked_for(
        qtbot, tmp_path):
    client = _client()
    client.forget_history = MagicMock()
    now = [1000.0]
    queue = JobQueue(Database(tmp_path / "test.db"), client, clock=lambda: now[0])
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    image = _launch_image(queue, "i")
    now[0] = 1010.0
    image.finished.emit([{"filename": "out.png"}], None, 1.0)

    assert client.submit_job.call_args_list[-1].args[1] == image.prompt_id

    now[0] = 1060.0
    queue._videos_wait.timeout.emit()  # the minute is up, delivered the way the timer does

    assert [c.args[1] for c in client.submit_job.call_args_list] == [
        video.prompt_id, image.prompt_id, video.prompt_id
    ]
    assert queue.queue_order == [video.prompt_id]


def _a_video_waiting_on_an_image(tmp_path, now):
    """A video set aside for an image asked for at ``now``, the image done
    ten seconds later: the video is waiting out the rest of the minute."""
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client, clock=lambda: now[0])
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    image = _launch_image(queue, "i")
    now[0] += 10
    image.finished.emit([{"filename": "out.png"}], None, 1.0)
    return client, queue, video


def test_the_wait_is_timed_for_what_is_left_of_the_minute(qtbot, tmp_path):
    _client_, queue, _video = _a_video_waiting_on_an_image(tmp_path, [1000.0])

    assert queue._videos_wait.isActive()
    assert queue._videos_wait.interval() == 50_000


def test_an_image_asked_for_during_the_wait_starts_at_once_and_the_minute_starts_again(
        qtbot, tmp_path):
    now = [1000.0]
    client, queue, video = _a_video_waiting_on_an_image(tmp_path, now)
    now[0] = 1030.0

    another = _launch_image(queue, "i2")

    assert client.submit_job.call_args_list[-1].args[1] == another.prompt_id
    another.finished.emit([{"filename": "out.png"}], None, 1.0)
    now[0] = 1060.0
    queue._videos_wait.timeout.emit()
    assert client.submit_job.call_args_list[-1].args[1] == another.prompt_id
    assert queue._videos_wait.interval() == 30_000
    now[0] = 1090.0
    queue._videos_wait.timeout.emit()
    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id


def test_the_video_waiting_out_the_minute_says_when_it_starts(qtbot, tmp_path):
    _client_, queue, video = _a_video_waiting_on_an_image(tmp_path, [1000.0])

    assert queue.starts_at(video.prompt_id) == 1060.0


def test_a_video_set_aside_says_no_start_while_the_image_is_being_made(qtbot, tmp_path):
    # Until the image is done it is the image the video waits on, which
    # has its own bar; a start time would be a promise the image could break.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client, clock=lambda: 1000.0)
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    _launch_image(queue, "i")

    assert queue.starts_at(video.prompt_id) is None


def test_start_now_starts_the_video_waiting_out_the_minute_at_once(qtbot, tmp_path):
    client, queue, video = _a_video_waiting_on_an_image(tmp_path, [1000.0])

    queue.start_now()

    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id
    assert not queue._videos_wait.isActive()


def test_a_video_held_for_a_training_says_no_start(qtbot, tmp_path):
    _client_, queue, video = _a_video_waiting_on_an_image(tmp_path, [1000.0])

    queue.watch_training(_Training())

    assert queue.starts_at(video.prompt_id) is None


def test_only_the_video_at_the_front_says_when_it_starts(qtbot, tmp_path):
    now = [1000.0]
    _client_, queue, _video = _a_video_waiting_on_an_image(tmp_path, now)

    behind = _launch_video(queue, "v2", seed=2)

    assert queue.starts_at(behind.prompt_id) is None


def test_a_video_waiting_out_the_minute_goes_to_comfyui_as_the_app_closes(qtbot, tmp_path):
    client, queue, video = _a_video_waiting_on_an_image(tmp_path, [1000.0])

    assert queue.flush_to_server() == 1
    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id


def test_a_video_set_aside_shows_as_one_that_has_not_started(qtbot, tmp_path):
    # Its row goes back to pending -- a restart re-adopts it into the line rather
    # than looking for it on a server that no longer has it -- and the progress
    # persisted for the stopped run goes with it.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    queue._persist_progress(video)
    assert db.get_generation(video.prompt_id)["progress_json"]

    _launch_image(queue, "i")

    row = db.get_generation(video.prompt_id)
    assert row["status"] == "pending"
    assert row["progress_json"] is None
    assert video.state == "idle"
    assert video.started_at is None


def test_a_video_asked_for_leaves_a_video_being_rendered_alone(qtbot, tmp_path):
    # Asking for a video is asking for "later".
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "v1", seed=1)
    _rendering(client, rendering)

    later = _launch_video(queue, "v2", seed=2)

    client.interrupt.assert_not_called()
    assert queue.queue_order == [rendering.prompt_id, later.prompt_id]


def test_a_videos_start_frame_being_drawn_is_set_aside_with_the_videos(qtbot, tmp_path):
    # The prompt on the GPU is a still, but the run it opens is a video, and it
    # rejoins the line as one: after the image, ahead of the videos waiting.
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    image = _image_row()
    db.restore_generation(image)
    queue.start_reroll("k", gallery.SettingsGroup("k", "settings", [_video_row()]), [image])
    frame = queue.newest_job_for("k")
    waiting = _launch_video(queue, "v", seed=1)
    _rendering(client, frame)

    image = _launch_image(queue, "i")

    client.interrupt.assert_called_once_with(frame.prompt_id)
    assert queue.queue_order == [image.prompt_id, frame.prompt_id, waiting.prompt_id]


def test_an_image_being_rendered_is_set_aside_right_after_the_newer_one(qtbot, tmp_path):
    # Anything on the GPU yields to the user's image work, an image included:
    # it was the front until the newer one took it, so it goes right after it,
    # ahead of the images asked for before it.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    oldest = _launch_image(queue, "i1", seed=1)
    middle = _launch_image(queue, "i2", seed=2)   # takes the machine from oldest
    _rendering(client, middle)

    newest = _launch_image(queue, "i3", seed=3)

    assert [c.args[0] for c in client.interrupt.call_args_list] == [
        oldest.prompt_id, middle.prompt_id
    ]
    assert queue.queue_order == [newest.prompt_id, middle.prompt_id, oldest.prompt_id]


def test_a_batch_of_images_is_made_in_the_order_asked_without_stopping_itself(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)

    launched = queue.start_batch("k", WORKFLOW_REGISTRY[_IMAGE_WF],
                                 [_image_params(seed=seed) for seed in (1, 2, 3)])

    client.interrupt.assert_not_called()
    client.submit_job.assert_called_once()
    assert queue.queue_order == launched
    assert [queue.job_for_prompt(pid).params["seed"] for pid in launched] == [1, 2, 3]


def test_what_a_batch_of_images_takes_the_machine_from_waits_for_the_whole_batch(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_image(queue, "i", seed=9)
    _rendering(client, rendering)

    launched = queue.start_batch("k", WORKFLOW_REGISTRY[_IMAGE_WF],
                                 [_image_params(seed=seed) for seed in (1, 2)])

    client.interrupt.assert_called_once_with(rendering.prompt_id)
    assert queue.queue_order == [*launched, rendering.prompt_id]


def test_a_batch_of_videos_joins_the_back_of_the_line_in_the_order_asked(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "v", seed=9)
    _rendering(client, rendering)

    launched = queue.start_batch("k", _I2V, [_params(seed=seed) for seed in (1, 2)])

    client.interrupt.assert_not_called()
    assert queue.queue_order == [rendering.prompt_id, *launched]


def test_a_batch_names_none_where_an_entry_did_not_go(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    client.submit_job.side_effect = [RuntimeError("refused"), "comfy-X"]

    launched = queue.start_batch("k", WORKFLOW_REGISTRY[_IMAGE_WF],
                                 [_image_params(seed=seed) for seed in (1, 2)])

    assert launched[0] is None
    assert queue.queue_order == [launched[1]]


def test_a_repair_being_rendered_is_set_aside_to_the_back(qtbot, tmp_path):
    # A base re-render adopted from the last absence is work nobody asked for:
    # it yields like anything else, and goes back to where it joined.
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    queue.start_prepared("r", WORKFLOW_REGISTRY[_IMAGE_WF], _image_params(),
                              source="base_render")
    repair = queue.newest_job_for("r")
    waiting = _launch_video(queue, "v", seed=1)
    _rendering(client, repair)

    image = _launch_image(queue, "i")

    client.interrupt.assert_called_once_with(repair.prompt_id)
    assert queue.queue_order == [image.prompt_id, waiting.prompt_id, repair.prompt_id]


def test_work_nobody_asked_for_takes_the_machine_from_nothing(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "v", seed=1)
    _rendering(client, rendering)

    queue.start_prepared("e", WORKFLOW_REGISTRY[_IMAGE_WF], _image_params(),
                              source="experiment")

    client.interrupt.assert_not_called()
    assert queue.queue_order[0] == rendering.prompt_id


def test_every_video_the_server_holds_is_pulled_back_for_the_image(qtbot, tmp_path):
    # After a restart the server can hold several of ours -- one rendering, the
    # rest queued after it there, where the image would wait on all of them.
    # They come back in the order they were in, ahead of any video waiting here.
    client = _client()
    client.executing_prompts.return_value = {"v-old"}
    db = Database(tmp_path / "test.db")
    for pid in ("v-old", "v-new"):
        db.insert_generation(prompt_id=pid, workflow_name="wan22_i2v",
                             workflow_version=_I2V.version, positive_prompt="x", seed=1,
                             params_json=json.dumps(_params(seed=1)), workflow_json="{}")
        db.update_generation(pid, status="running")
    queue = JobQueue(db, client)
    queue.reconnect_running()

    image = _launch_image(queue, "i")

    assert sorted(c.args[0] for c in client.cancel_prompt.call_args_list) == ["v-new", "v-old"]
    assert sorted(c.args[0] for c in client.interrupt.call_args_list) == ["v-new", "v-old"]
    assert queue.queue_order == [image.prompt_id, "v-old", "v-new"]


def test_a_restart_takes_back_every_job_comfyui_holds_but_is_not_making(qtbot, tmp_path):
    client = _client()
    client.executing_prompts = MagicMock(return_value={"v-old"})
    db = Database(tmp_path / "test.db")
    for pid in ("v-old", "v-new"):
        db.insert_generation(prompt_id=pid, workflow_name="wan22_i2v",
                             workflow_version=_I2V.version, positive_prompt="x", seed=1,
                             params_json=json.dumps(_params(seed=1)), workflow_json="{}")
        db.update_generation(pid, status="running")
    queue = JobQueue(db, client)

    queue.reconnect_running()

    assert queue.queue_order == ["v-old", "v-new"]
    assert [c.args[0] for c in client.cancel_prompt.call_args_list] == ["v-new"]
    assert db.get_generation("v-new")["status"] == "pending"
    assert db.get_generation("v-old")["status"] == "running"


def test_the_run_comfyui_is_making_is_the_front_of_the_line(qtbot, tmp_path):
    # Taken back after a restart, the runs the server holds come back oldest
    # first, which need not be the order it makes them in.
    client = _client()
    client.executing_prompts.return_value = {"v-new"}
    db = Database(tmp_path / "test.db")
    for pid in ("v-old", "v-new"):
        db.insert_generation(prompt_id=pid, workflow_name="wan22_i2v",
                             workflow_version=_I2V.version, positive_prompt="x", seed=1,
                             params_json=json.dumps(_params(seed=1)), workflow_json="{}")
        db.update_generation(pid, status="running")
    queue = JobQueue(db, client)
    queue.reconnect_running()

    client.progress.emit("v-new", "s", 1, 10)

    assert queue.queue_order == ["v-new", "v-old"]


def test_a_video_set_aside_that_had_finished_after_all_lands_instead_of_running_again(
        qtbot, tmp_path):
    # The stop can reach the server after the video's last node has saved. Then
    # the file exists, and its turn coming round again is when that is found.
    client = _client()
    db = Database(tmp_path / "test.db")
    now = [1000.0]
    queue = JobQueue(db, client, clock=lambda: now[0])
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    image = _launch_image(queue, "i")
    client.fetch_history = MagicMock(return_value={"outputs": {
        _I2V.output_node_id: {"gifs": [{"filename": "out.mp4", "subfolder": ""}]},
    }})
    client.forget_history = MagicMock()
    image.finished.emit([{"filename": "out.png"}], None, 1.0)

    now[0] = 1060.0
    queue._videos_wait.timeout.emit()

    assert client.submit_job.call_count == 2  # the video's first send, and the image
    assert db.get_generation(video.prompt_id)["status"] == "completed"
    assert queue.queue_order == []


def test_an_image_asked_for_while_a_videos_hand_over_is_out_takes_the_machine_when_it_lands(
        qtbot, tmp_path):
    # The server can take a minute to accept a prompt. An image asked for in
    # that minute cannot take the machine from a video that is not on it yet,
    # so it takes it the moment the video lands, as one asked for later would.
    client, gate = _gated_client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    seen = {}

    def while_the_submit_is_out():
        seen["image"] = _launch_image(queue, "i")
        gate.set()

    QTimer.singleShot(0, while_the_submit_is_out)
    video = _launch_video(queue, "v", seed=1)

    client.interrupt.assert_called_once_with(video.prompt_id)
    assert [c.args[1] for c in client.submit_job.call_args_list] == [
        video.prompt_id, seen["image"].prompt_id
    ]
    assert queue.queue_order == [seen["image"].prompt_id, video.prompt_id]


# --- what a slideshow is locked on is made first --------------------------------

def test_a_job_put_first_leads_the_line_and_takes_the_machine(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    oldest = _launch_image(queue, "i1", seed=1)
    middle = _launch_image(queue, "i2", seed=2)
    newest = _launch_image(queue, "i3", seed=3)
    _rendering(client, newest)

    queue.put_first({oldest.prompt_id})

    assert client.interrupt.call_args_list[-1].args[0] == newest.prompt_id
    assert client.submit_job.call_args_list[-1].args[1] == oldest.prompt_id
    assert queue.queue_order == [oldest.prompt_id, newest.prompt_id, middle.prompt_id]


def test_an_image_asked_for_leaves_a_job_put_first_on_the_machine(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    locked = _launch_image(queue, "i1", seed=1)
    _rendering(client, locked)
    queue.put_first({locked.prompt_id})

    newer = _launch_image(queue, "i2", seed=2)

    client.interrupt.assert_not_called()
    assert queue.queue_order == [locked.prompt_id, newer.prompt_id]


def test_an_image_asked_for_joins_behind_every_job_put_first(qtbot, tmp_path):
    queue = JobQueue(Database(tmp_path / "test.db"), _client())
    waiting = _launch_image(queue, "i1", seed=1)
    rendering = _launch_image(queue, "i2", seed=2)
    queue.put_first({waiting.prompt_id, rendering.prompt_id})

    newer = _launch_image(queue, "i3", seed=3)

    assert queue.queue_order == [rendering.prompt_id, waiting.prompt_id, newer.prompt_id]


def test_a_batch_of_images_lines_up_after_a_job_put_first_and_leaves_it_running(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    locked = _launch_image(queue, "i1", seed=1)
    _rendering(client, locked)
    queue.put_first({locked.prompt_id})

    launched = queue.start_batch("k", WORKFLOW_REGISTRY[_IMAGE_WF],
                                 [_image_params(seed=seed) for seed in (2, 3)])

    client.interrupt.assert_not_called()
    assert queue.queue_order == [locked.prompt_id, *launched]


def test_the_image_set_aside_for_a_job_put_first_goes_back_behind_all_of_them(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    oldest = _launch_image(queue, "i1", seed=1)
    middle = _launch_image(queue, "i2", seed=2)
    newest = _launch_image(queue, "i3", seed=3)
    _rendering(client, newest)

    queue.put_first({oldest.prompt_id, middle.prompt_id})

    assert queue.queue_order == [middle.prompt_id, oldest.prompt_id, newest.prompt_id]


def test_a_job_put_first_while_a_hand_over_is_out_takes_the_machine_when_it_lands(
        qtbot, tmp_path):
    client, gate = _gated_client()
    gate.set()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    locked = _launch_image(queue, "i1", seed=1)
    handed_over_next = _launch_image(queue, "i2", seed=2)
    rendering = _launch_image(queue, "i3", seed=3)
    gate.clear()

    def while_the_submit_is_out():
        queue.put_first({locked.prompt_id})
        gate.set()

    QTimer.singleShot(0, while_the_submit_is_out)
    rendering.finished.emit([{"filename": "out.png"}], None, 1.0)

    client.interrupt.assert_called_with(handed_over_next.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == locked.prompt_id
    assert queue.queue_order == [locked.prompt_id, handed_over_next.prompt_id]


# --- a shielded run keeps the machine until it is done ---------------------------

def test_an_image_asked_for_waits_behind_a_shielded_video_being_rendered(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    queue.shield(video.prompt_id, True)

    image = _launch_image(queue, "i")

    client.interrupt.assert_not_called()
    assert queue.queue_order == [video.prompt_id, image.prompt_id]


def test_what_a_slideshow_locks_on_waits_behind_a_shielded_run_being_rendered(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    video = _launch_video(queue, "v1", seed=1)
    _rendering(client, video)
    queue.shield(video.prompt_id, True)
    locked = _launch_video(queue, "v2", seed=2)

    queue.put_first({locked.prompt_id})

    client.interrupt.assert_not_called()
    assert queue.queue_order == [video.prompt_id, locked.prompt_id]


def test_a_shield_on_the_run_being_made_survives_a_restart(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, _client())
    video = _launch_video(queue, "v", seed=1)
    queue.shield(video.prompt_id, True)

    restarted = JobQueue(db, _client())
    restarted.reconnect_running()

    assert restarted.job_for_prompt(video.prompt_id).shielded


def test_a_shield_on_a_run_still_waiting_survives_a_restart(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, _client())
    _launch_video(queue, "v1", seed=1)
    waiting = _launch_video(queue, "v2", seed=2)
    queue.shield(waiting.prompt_id, True)

    restarted = JobQueue(db, _client())
    restarted.reconnect_running()

    assert restarted.job_for_prompt(waiting.prompt_id).shielded


def test_a_user_launch_leaves_a_shielded_experiment_running(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    queue.start_prepared("exp-key", _I2V, _params(), source="experiment")
    experiment = queue.job_for("exp-key")
    _rendering(client, experiment)
    queue.shield(experiment.prompt_id, True)

    queue.start_prepared("user-key", _I2V, _params(seed=7))

    client.interrupt.assert_not_called()
    assert queue.has("exp-key")


def test_a_shield_on_a_videos_start_frame_stays_on_the_video_made_from_it(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    image = _image_row()
    db.restore_generation(image)
    queue.start_reroll("k", gallery.SettingsGroup("k", "settings", [_video_row()]), [image])
    frame = queue.newest_job_for("k")
    queue.shield(frame.prompt_id, True)

    frame.finished.emit([{"filename": "frame_002.png", "subfolder": "", "type": "output"}],
                        None, 1.0)

    video = queue.newest_job_for("k")
    assert video is not frame and video.shielded
    assert db.get_generation(video.prompt_id)["shielded"]


def test_taking_the_shield_off_hands_the_machine_to_the_image_waiting_behind_it(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    video = _launch_video(queue, "v", seed=1)
    _rendering(client, video)
    queue.shield(video.prompt_id, True)
    image = _launch_image(queue, "i")

    queue.shield(video.prompt_id, False)

    client.interrupt.assert_called_once_with(video.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == image.prompt_id
    assert queue.queue_order == [image.prompt_id, video.prompt_id]


def test_taking_the_shield_off_hands_the_machine_to_what_a_slideshow_is_locked_on(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    video = _launch_video(queue, "v1", seed=1)
    _rendering(client, video)
    queue.shield(video.prompt_id, True)
    locked = _launch_video(queue, "v2", seed=2)
    queue.put_first({locked.prompt_id})

    queue.shield(video.prompt_id, False)

    client.interrupt.assert_called_once_with(video.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == locked.prompt_id
    assert queue.queue_order == [locked.prompt_id, video.prompt_id]


def test_taking_the_shield_off_with_only_videos_waiting_leaves_the_run_going(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    video = _launch_video(queue, "v1", seed=1)
    _rendering(client, video)
    queue.shield(video.prompt_id, True)
    later = _launch_video(queue, "v2", seed=2)

    queue.shield(video.prompt_id, False)

    client.interrupt.assert_not_called()
    assert queue.queue_order == [video.prompt_id, later.prompt_id]


# --- a video waits for the enhancement of the image it starts from ----------

_ENHANCE = WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW]
_IMAGE = "image/image_00001_.png [output]"
_ENHANCED = {"filename": "image_enhance_00001_.png", "subfolder": "image", "type": "output"}
_ENHANCED_REF = "image/image_enhance_00001_.png [output]"


def _launch_enhance(queue, key, image=_IMAGE):
    queue.start_prepared(key, _ENHANCE, {**_ENHANCE.default_params(), "input_image": image})
    return queue.newest_job_for(key)


def _a_minute_later(queue, now):
    """The minute a video waits after the last image asked for, here an
    enhancement, gone by, and the timer's call delivered."""
    now[0] += 60
    queue._videos_wait.timeout.emit()


def test_a_video_asked_for_while_its_image_is_enhanced_is_made_from_the_enhancement(
        qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    now = [1000.0]
    queue = JobQueue(db, client, clock=lambda: now[0])
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)

    enhance.finished.emit([_ENHANCED], None, 1.0)
    _a_minute_later(queue, now)

    payload, prompt_id = client.submit_job.call_args_list[-1].args
    assert prompt_id == video.prompt_id
    assert _ENHANCED_REF in json.dumps(payload)
    row = db.get_generation(video.prompt_id)
    assert json.loads(row["params_json"])["input_image"] == _ENHANCED_REF
    assert json.loads(row["workflow_json"]) == payload


def test_the_video_waiting_on_an_enhancement_is_sent_after_the_enhancement_is_announced(
        qtbot, tmp_path):
    client = _client()
    now = [1000.0]
    queue = JobQueue(Database(tmp_path / "test.db"), client, clock=lambda: now[0])
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)
    now[0] += 120  # the enhancement asked for long ago: no minute left to wait
    sent_by_the_announcement = []
    queue.finished.connect(
        lambda *_: sent_by_the_announcement.append(client.submit_job.call_count))

    enhance.finished.emit([_ENHANCED], None, 1.0)

    assert sent_by_the_announcement == [1]
    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id


def test_a_video_moved_ahead_of_its_images_enhancement_still_comes_after_it(
        qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    locked = _launch_image(queue, "i", seed=1)
    queue.put_first({locked.prompt_id})
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)

    queue.move(video.prompt_id, before=enhance.prompt_id)

    assert queue.queue_order == [locked.prompt_id, enhance.prompt_id, video.prompt_id]


def test_a_video_moved_to_the_top_takes_its_images_enhancement_along(qtbot, tmp_path):
    client = _client()
    queue = JobQueue(Database(tmp_path / "test.db"), client)
    rendering = _launch_video(queue, "r", seed=1)
    _rendering(client, rendering)
    queue.shield(rendering.prompt_id, True)
    enhance = _launch_enhance(queue, "e")
    other = _launch_video(queue, "o", seed=2)
    video = _launch_video(queue, "v", input_image=_IMAGE)
    queue.move(other.prompt_id, before=enhance.prompt_id)
    queue.shield(rendering.prompt_id, False)

    queue.move(video.prompt_id, before=rendering.prompt_id)

    assert queue.queue_order == [enhance.prompt_id, video.prompt_id, rendering.prompt_id,
                                 other.prompt_id]
    client.interrupt.assert_called_once_with(rendering.prompt_id)
    assert client.submit_job.call_args_list[-1].args[1] == enhance.prompt_id


def test_closing_keeps_back_a_video_waiting_for_its_images_enhancement(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)
    other = _launch_video(queue, "w", input_image="image/another_00002_.png [output]")

    queue.flush_to_server()

    assert [call.args[1] for call in client.submit_job.call_args_list] == [
        enhance.prompt_id, other.prompt_id]
    assert db.get_generation(video.prompt_id)["status"] == "pending"


_PLAIN = {"filename": "image_00001_.png", "subfolder": "image", "type": "output"}


def _image(db, *, enhanced=False):
    """The image a video starts from, enhanced or still plain."""
    db.insert_generation(prompt_id="image", workflow_name=_IMAGE_WF, workflow_version="v",
                         params_json="{}", workflow_json="{}")
    db.update_generation(
        "image", status="completed",
        output_files=json.dumps([_ENHANCED, _PLAIN] if enhanced else [_PLAIN]),
        original_files=json.dumps([_PLAIN]) if enhanced else None)


def _enhanced_into(queue, enhanced):
    queue.enhance_images_with(lambda image: enhanced.append(image["prompt_id"]))
    return queue


def test_a_video_from_an_image_never_enhanced_has_the_image_enhanced_first(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db)
    enhanced = []
    queue = _enhanced_into(JobQueue(db, _client()), enhanced)

    _launch_video(queue, "v", input_image=_IMAGE)

    assert enhanced == ["image"]


def test_an_image_already_being_enhanced_is_not_enhanced_again_for_a_video(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db)
    enhanced = []
    queue = _enhanced_into(JobQueue(db, _client()), enhanced)
    _launch_enhance(queue, "e")

    _launch_video(queue, "v", input_image=_IMAGE)

    assert enhanced == []


def test_a_video_from_the_plain_version_of_an_enhanced_image_is_made_from_the_enhancement(
        qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    _image(db, enhanced=True)
    enhanced = []
    queue = _enhanced_into(JobQueue(db, client), enhanced)

    video = _launch_video(queue, "v", input_image=_IMAGE)

    payload, prompt_id = client.submit_job.call_args_list[-1].args
    assert prompt_id == video.prompt_id
    assert _ENHANCED_REF in json.dumps(payload)
    row = db.get_generation(video.prompt_id)
    assert json.loads(row["params_json"])["input_image"] == _ENHANCED_REF
    assert json.loads(row["workflow_json"]) == payload
    assert enhanced == []


def test_a_video_asked_for_on_an_enhancement_is_made_from_it_as_asked(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db, enhanced=True)
    enhanced = []
    queue = _enhanced_into(JobQueue(db, _client()), enhanced)

    video = _launch_video(queue, "v", input_image=_ENHANCED_REF)

    assert video.params["input_image"] == _ENHANCED_REF
    assert enhanced == []


def test_a_start_image_no_gallery_image_holds_is_made_from_as_it_is(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    _image(db)
    enhanced = []
    queue = _enhanced_into(JobQueue(db, _client()), enhanced)

    video = _launch_video(queue, "v", input_image="from_elsewhere.png")

    assert video.params["input_image"] == "from_elsewhere.png"
    assert enhanced == []


def test_a_video_whose_start_image_is_sent_for_enhancement_waits_and_is_made_from_it(
        qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    _image(db)
    now = [1000.0]
    queue = JobQueue(db, client, clock=lambda: now[0])
    queue.enhance_images_with(lambda image: _launch_enhance(queue, "e"))

    video = _launch_video(queue, "v", input_image=_IMAGE)
    enhance = queue.newest_job_for("e")
    enhance.finished.emit([_ENHANCED], None, 1.0)
    _a_minute_later(queue, now)

    assert [call.args[1] for call in client.submit_job.call_args_list] == [
        enhance.prompt_id, video.prompt_id]
    assert _ENHANCED_REF in json.dumps(client.submit_job.call_args_list[-1].args[0])


def test_a_video_held_over_a_restart_starts_from_the_enhancement_its_image_gained(
        qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    _pending_row(db, "video", params=_params(input_image=_IMAGE))
    _image(db, enhanced=True)
    queue = _enhanced_into(JobQueue(db, client), [])

    queue.reconnect_running()

    assert _ENHANCED_REF in json.dumps(client.submit_job.call_args_list[-1].args[0])
    assert json.loads(db.get_generation("video")["params_json"])["input_image"] == _ENHANCED_REF


def test_a_video_held_over_a_restart_does_not_ask_again_for_the_enhance_a_newer_row_holds(
        qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    _pending_row(db, "video", params=_params(input_image=_IMAGE))
    _pending_row(db, "enhance", workflow_name=gallery.ENHANCE_WORKFLOW,
                 params={**_ENHANCE.default_params(), "input_image": _IMAGE})
    db.update_generation("enhance", status="running")
    _image(db)
    enhanced = []
    queue = _enhanced_into(JobQueue(db, _client()), enhanced)

    queue.reconnect_running()

    assert enhanced == []


def test_a_video_waiting_on_an_enhancement_that_fails_fails_with_it(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    failed = []
    queue.failed.connect(lambda key, message: failed.append(key))
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)

    enhance.failed.emit("the sampler ran out of memory")

    assert [call.args[1] for call in client.submit_job.call_args_list] == [enhance.prompt_id]
    assert db.get_generation(video.prompt_id)["status"] == "error"
    assert failed == ["e", "v"]


def test_cancelling_the_enhancement_a_video_waits_on_cancels_the_video_too(qtbot, tmp_path):
    client = _client()
    db = Database(tmp_path / "test.db")
    queue = JobQueue(db, client)
    enhance = _launch_enhance(queue, "e")
    video = _launch_video(queue, "v", input_image=_IMAGE)

    queue.cancel_job(enhance.prompt_id)

    assert [call.args[1] for call in client.submit_job.call_args_list] == [enhance.prompt_id]
    assert db.get_generation(video.prompt_id) is None
    assert queue.all_jobs == []
