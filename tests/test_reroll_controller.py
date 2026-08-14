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


def test_an_interrupted_job_lands_as_an_error_not_a_completion(qtbot, tmp_path):
    # A cancel from outside this job (ComfyUI's own UI, a second app instance)
    # ends the prompt the way a success ends it, with a history carrying no
    # outputs. The row must record the failure: a 'completed' row with no file is
    # invisible in the gallery yet still refuses a re-run of those settings as a
    # duplicate — the state the user hits as "it says it exists already".
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("video/wf/deadbeef", _I2V, _params(seed=3, noise_seed=9))
    prompt_id = controller.jobs["video/wf/deadbeef"].prompt_id

    client.job_completed.emit(prompt_id, {"outputs": {}})

    row = db.get_generation(prompt_id)
    assert row["status"] == "error"
    assert not json.loads(row["output_files"] or "[]")
    assert "video/wf/deadbeef" not in controller.jobs


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


def test_a_second_user_launch_joins_a_folder_already_running(qtbot, tmp_path):
    # Two pictures of one recipe, both wanted: the second queues behind the first
    # rather than being refused, which is what stopped them being made together.
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)
    controller.start_prepared("k", _I2V, _params(seed=3))

    again = controller.start_prepared("k", _I2V, _params(seed=99))

    assert again is True
    assert len(controller.all_jobs) == 2
    assert client.submit_job.call_count == 2


def test_the_folders_live_tile_still_follows_the_job_in_front(qtbot, tmp_path):
    # Things keyed by folder — the one live re-roll tile, the selection that
    # follows it — show the leading job, not a second one queued behind it.
    controller = RerollController(Database(tmp_path / "test.db"), _client())
    controller.start_prepared("k", _I2V, _params(seed=3))
    leader = controller.job_for("k")
    controller.start_prepared("k", _I2V, _params(seed=99))

    assert controller.job_for("k") is leader
    assert controller.jobs == {"k": leader}
    assert controller.has("k") is True


def test_an_experiment_never_stacks_onto_a_busy_folder(qtbot, tmp_path):
    # Only work the user asked for may queue up; the background experimenter still
    # takes an idle folder or none at all.
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)
    controller.start_prepared("k", _I2V, _params(seed=3))

    again = controller.start_prepared("k", _I2V, _params(seed=99), source="experiment")

    assert again is False
    client.submit_job.assert_called_once()


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


def test_a_second_chained_reroll_queues_behind_the_first(qtbot, tmp_path):
    # A chained image→video re-roll stacks like any other user launch now.
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)
    image_wf = WORKFLOW_REGISTRY[_IMAGE_WF]
    controller.start_reroll_from_image("k", _image_row(), image_wf, _I2V, _params())

    again = controller.start_reroll_from_image("k", _image_row(), image_wf, _I2V, _params())

    assert again is True
    assert client.submit_job.call_count == 2


# --- user work preempts background experiments --------------------------------

def test_user_launch_preempts_a_running_experiment(qtbot, tmp_path):
    # A video experiment can hold the GPU for many minutes; a user's Generate must
    # kick it off rather than silently queue behind it with a dead progress bar.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("exp-key", _I2V, _params(), source="experiment")
    experiment = controller.job_for("exp-key")
    client.progress.emit(experiment.prompt_id, 1, 10)  # ComfyUI began executing it

    started = controller.start_prepared("user-key", _I2V, _params(seed=7))

    assert started is True
    client.interrupt.assert_called_once()              # the running experiment was stopped
    assert not controller.has("exp-key")
    assert db.get_generation(experiment.prompt_id) is None  # its abandoned row is dropped
    assert controller.has("user-key")


def test_user_launch_dequeues_a_still_queued_experiment(qtbot, tmp_path):
    # An experiment ComfyUI hasn't started yet is removed from the queue (not
    # interrupted — that would kill whatever IS executing).
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("exp-key", _I2V, _params(), source="experiment")
    experiment = controller.job_for("exp-key")

    controller.start_prepared("user-key", _I2V, _params(seed=7))

    client.cancel_prompt.assert_called_once_with(experiment.prompt_id)
    client.interrupt.assert_not_called()


def test_per_seed_rerolls_preempt_experiments_too(qtbot, tmp_path):
    # Every user path funnels through the same launch choke point, so a per-item
    # seed re-roll clears the experimenter exactly as the Generate button does.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("exp-key", _I2V, _params(), source="experiment")

    controller.reroll_video_seed("k", _video_row())

    assert not controller.has("exp-key")
    assert controller.has("k")


def test_an_experiment_launch_never_preempts(qtbot, tmp_path):
    # Only user work owns the GPU; a background experiment never bumps anything.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("exp-1", _I2V, _params(), source="experiment")

    controller.start_prepared("exp-2", _I2V, _params(seed=5), source="experiment")

    client.interrupt.assert_not_called()
    client.cancel_prompt.assert_not_called()
    assert controller.has("exp-1")


def test_user_launch_claims_the_experiments_own_folder(qtbot, tmp_path):
    # Even when the user's settings land in the very folder the experiment runs
    # in, their Generate preempts it and takes the slot — not a silent no-op.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    controller.start_prepared("k", _I2V, _params(), source="experiment")

    started = controller.start_prepared("k", _I2V, _params(seed=7))

    assert started is True
    assert controller.job_for("k").source == "generated"
    assert client.submit_job.call_count == 2


def test_reconnected_experiments_stay_preemptible(qtbot, tmp_path):
    # Opening the app drops the batch the last absence queued, but one ComfyUI
    # refused to dequeue survives that sweep and is adopted as a live job. It
    # reconnects with its row's source, so the first user launch still clears it.
    client = _client()
    db = Database(tmp_path / "test.db")
    controller = RerollController(db, client)
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    db.insert_generation(prompt_id="exp-rr", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="x", seed=1,
                         params_json=json.dumps({**wf.default_params(), "seed": 1}),
                         workflow_json="{}", source="experiment")
    db.update_generation("exp-rr", status="running")
    controller.reconnect_running()

    controller.start_prepared("user-key", _I2V, _params(seed=7))

    client.interrupt.assert_called_once()  # reconnected jobs report as running
    assert db.get_generation("exp-rr") is None


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


# --- the order ComfyUI will work through the queue in -------------------------

def test_queue_order_starts_out_empty(qtbot, tmp_path):
    controller = RerollController(Database(tmp_path / "test.db"), _client())
    assert controller.queue_order == []


def test_refresh_reads_the_order_from_comfyui(qtbot, tmp_path):
    client = _client()
    client.queue_order = MagicMock(return_value=["b", "a"])
    controller = RerollController(Database(tmp_path / "test.db"), client)

    controller.refresh_queue_order()

    assert controller.queue_order == ["b", "a"]


def test_an_unreadable_queue_leaves_the_last_known_order(qtbot, tmp_path):
    # Dropping to no order at all would reshuffle the strip on screen every time
    # ComfyUI hiccups; the order it last gave is still the best answer there is.
    client = _client()
    client.queue_order = MagicMock(return_value=["b", "a"])
    controller = RerollController(Database(tmp_path / "test.db"), client)
    controller.refresh_queue_order()

    client.queue_order = MagicMock(side_effect=OSError("connection refused"))
    controller.refresh_queue_order()

    assert controller.queue_order == ["b", "a"]


def test_refresh_without_a_client_is_harmless(qtbot, tmp_path):
    controller = RerollController(Database(tmp_path / "test.db"), None)
    controller.refresh_queue_order()
    assert controller.queue_order == []


# --- reordering what ComfyUI has waiting --------------------------------------

def _three_queued(tmp_path):
    """A controller holding three queued jobs, and their prompt ids in queue order."""
    client = _client()
    controller = RerollController(Database(tmp_path / "test.db"), client)
    for i in range(3):
        controller.start_prepared(f"k{i}", _I2V, _params(seed=i))
    ids = [controller.job_for(f"k{i}").prompt_id for i in range(3)]
    client.queue_order = MagicMock(return_value=list(ids))
    client.cancel_prompt.reset_mock()
    client.submit_job.reset_mock()
    return controller, client, ids


def test_reorder_requeues_only_from_where_the_order_first_differs(qtbot, tmp_path):
    # Dragging the last job above the middle one leaves the head alone: requeuing
    # a job that hasn't moved would push it behind another app's work for nothing.
    controller, client, (a, b, c) = _three_queued(tmp_path)

    controller.reorder([a, c, b])

    assert [call.args[1] for call in client.submit_job.call_args_list] == [c, b]
    assert [call.args[0] for call in client.cancel_prompt.call_args_list] == [c, b]


def test_reorder_that_changes_nothing_touches_the_queue(qtbot, tmp_path):
    controller, client, ids = _three_queued(tmp_path)

    controller.reorder(list(ids))

    client.cancel_prompt.assert_not_called()
    client.submit_job.assert_not_called()


def test_reorder_never_moves_the_job_comfyui_is_running(qtbot, tmp_path):
    # There is no place in front of what is executing, and dropping it would throw
    # the work away rather than reorder it.
    controller, client, (a, b, c) = _three_queued(tmp_path)
    client.progress.emit(a, 1, 10)  # ComfyUI started the head of the queue

    controller.reorder([c, a, b])

    assert a not in [call.args[1] for call in client.submit_job.call_args_list]


def test_reorder_ignores_ids_this_app_holds_no_job_for(qtbot, tmp_path):
    # Another app's prompts share the queue; nothing here can move them.
    controller, client, (a, b, c) = _three_queued(tmp_path)

    controller.reorder(["some-other-apps-prompt", c, b, a])

    assert [call.args[1] for call in client.submit_job.call_args_list] == [c, b, a]


def test_reorder_is_a_noop_when_the_queue_cannot_be_read(qtbot, tmp_path):
    # Without knowing the order now, "from where it first differs" is unanswerable
    # — better to leave the queue alone than reshuffle it on a guess.
    controller, client, (a, b, c) = _three_queued(tmp_path)
    client.queue_order = MagicMock(side_effect=OSError("connection refused"))

    controller.reorder([c, b, a])

    client.cancel_prompt.assert_not_called()
    client.submit_job.assert_not_called()


def test_reorder_without_a_client_is_harmless(qtbot, tmp_path):
    controller = RerollController(Database(tmp_path / "test.db"), None)
    controller.reorder(["anything"])  # nothing to reorder, nothing to raise


def test_parse_progress_state_tolerates_absent_or_corrupt():
    from origenerator.gui.reroll_controller import _parse_progress_state
    assert _parse_progress_state(None) is None
    assert _parse_progress_state("") is None
    assert _parse_progress_state("not json") is None
    assert _parse_progress_state("[1, 2]") is None          # valid JSON, but not a dict
    assert _parse_progress_state('{"total": 20}') == {"total": 20}
