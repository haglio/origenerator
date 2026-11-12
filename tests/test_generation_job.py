from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.generation_state import GenerationStatus
from origenerator.gui import generation_job as generation_job_module
from origenerator.gui.generation_job import (
    GenerationJob,
    JobFolders,
    JobSpec,
    JobState,
    display_status,
)
from origenerator.gui.job_queue import _off_the_gui_thread
from origenerator.gui.job_records import insert_generation_row
from origenerator.gui.off_thread import run_off_thread
from origenerator.output_places import OutputPlaces
from origenerator.provenance import BASIS, WORKFLOW, WORKFLOW_VERSION
from origenerator.thumbnail import animated_thumbnail_path
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.comfyui_folders import SUITE_FOLDERS
from tests.media_files import write_mp4

SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]
I2V = WORKFLOW_REGISTRY["wan22_i2v"]
SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


def _client():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-A")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    client.fetch_history = MagicMock(return_value={})
    client.forget_history = MagicMock()
    return client


def _params_with_the_two_sampler_enhance_tail():
    return dict(SDXL.default_params(), enhance=True)


def _started_job(tmp_path):
    client = _client()
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job.start()
    return job, client


def test_a_jobs_payload_saves_into_the_folder_named_for_its_run(qtbot, tmp_path):
    job = GenerationJob(_client(), JobSpec(SDXL, SDXL.default_params(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))

    prefixes = {node["inputs"]["filename_prefix"] for node in job.payload.values()
                if "filename_prefix" in node.get("inputs", {})}
    assert prefixes == {f"origenerator/comfy-A/{SDXL.default_params()['filename_prefix']}"}


def test_start_submits_payload_under_our_prompt_id_and_queues(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.submit_job.assert_called_once_with(job.payload, "comfy-A")
    assert job.state == "queued"


@pytest.mark.parametrize("history", [{}, SDXL_HISTORY], ids=["sent", "already landed"])
def test_a_submit_run_off_the_window_touches_nothing_of_the_jobs_there(
        qtbot, tmp_path, monkeypatch, history):
    touched_on = []

    def set_state(job, state):
        touched_on.append(threading.get_ident())
        job.__dict__["_kept_state"] = state

    def attach(job):
        touched_on.append(threading.get_ident())
        wire_the_clients_signals(job)

    wire_the_clients_signals = GenerationJob._attach
    monkeypatch.setattr(GenerationJob, "_state", property(
        lambda job: job.__dict__["_kept_state"], set_state), raising=False)
    monkeypatch.setattr(GenerationJob, "_attach", attach)
    client = _client()
    client.fetch_history = MagicMock(return_value=history)
    job = GenerationJob(client, JobSpec(SDXL, SDXL.default_params()), JobFolders(
        places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job.sent.connect(lambda: touched_on.append(threading.get_ident()))
    job.finished.connect(lambda *told: touched_on.append(threading.get_ident()))

    job.start(_off_the_gui_thread)

    assert touched_on == [threading.get_ident()] * 4, (
        "the slow submit may run on another thread, while the job's signals and state are only "
        "ever touched on the thread that started it")


def test_a_launched_row_records_which_version_of_its_workflow_ran(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    job = GenerationJob(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail()), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))

    insert_generation_row(db, job)

    block = json.loads(db.get_generation(job.prompt_id)["provenance"])
    assert (block["app"], block[WORKFLOW], block[WORKFLOW_VERSION],
            block[BASIS]) == ("origenerator", "sdxl_t2i", SDXL.version,
                              "recorded")


def test_progress_for_our_id_marks_started_and_forwards(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    started, progress = [], []
    job.started.connect(lambda: started.append(True))
    job.progress.connect(lambda v, m: progress.append((v, m)))

    client.progress.emit("comfy-OTHER", "5", 5, 50)
    assert started == []
    assert progress == []

    client.progress.emit("comfy-A", "5", 5, 50)
    assert started == [True]
    assert progress == [(2, 35)], (
        "five steps of a 50-step base pass, in a run budgeted for that pass and the 20-step enhance pass "
        "together; nothing in the app turns that enhance on by hand any more, but a reused old run still builds it")
    assert job.state == "running"
    assert job.last_progress == (2, 35)

    client.progress.emit("comfy-A", "5", 7, 50)
    assert started == [True]


def test_progress_accumulates_across_sampler_stages(qtbot, tmp_path):
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    client = _client()
    job = GenerationJob(client, JobSpec(wf, {**wf.default_params(), "steps": 20}, prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job.start()
    seen = []
    job.progress.connect(lambda v, m: seen.append((v, m)))

    client.progress.emit("comfy-A", "15", 10, 10)
    client.progress.emit("comfy-A", "16", 1, 10)

    assert seen == [(405, 810), (446, 810)], (
        "two video passes of ten steps, twenty in all, and no audio pass while audio is off")
    assert job.last_progress == (446, 810)
    assert job.last_pass_progress == (1, 10)
    assert job.last_stage == "Second pass", (
        "no executing word came for this node, as for a job joined mid-node after a restart, so its first "
        "tick names the stage; unnamed, the pass's own bar says only that something started over")


def test_a_single_pass_job_reports_no_pass_of_its_own(qtbot, tmp_path):
    wf = WORKFLOW_REGISTRY["flux_t2i_upscaled"]
    client = _client()
    job = GenerationJob(client, JobSpec(wf, wf.default_params(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job.start()

    client.progress.emit("comfy-A", "8", 5, 20)
    assert job.last_progress == (2, 10), (
        "a still's 20 steps are budgeted at half a second each, and five of them are done")
    assert job.last_pass_progress is None


def test_the_stage_is_named_from_the_first_node_long_before_any_step(qtbot, tmp_path):
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    client = _client()
    job = GenerationJob(client, JobSpec(wf, wf.default_params(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job.start()

    client.node_executing.emit("comfy-A", "4")
    assert job.last_stage == "Loading models", (
        "a WAN video spends over a minute loading its models before it reports a step")
    client.node_executing.emit("comfy-A", "12")
    assert job.last_stage == "Loading the image"
    client.node_executing.emit("comfy-A", "8")
    assert job.last_stage == "Loading the image", (
        "a caption that empties between two named stages reads as a run that lost its way")
    client.node_executing.emit("comfy-A", "17")
    assert job.last_stage == "Decoding frames"


def test_node_executing_for_our_id_marks_started(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    started = []
    job.started.connect(lambda: started.append(True))
    client.node_executing.emit("comfy-A", "5")
    assert started == [True]
    assert job.state == "running"


def test_preview_for_our_id_is_forwarded_and_cached(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    previews = []
    job.preview.connect(previews.append)

    client.preview_image.emit("comfy-OTHER", b"nope")
    assert previews == []

    client.preview_image.emit("comfy-A", b"IMG")
    assert previews == [b"IMG"]
    assert job.last_preview == b"IMG"
    assert job.state == "running"


def test_completion_for_our_id_emits_finished(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append((files, thumb, dur)))

    client.job_completed.emit("comfy-OTHER", SDXL_HISTORY)
    assert finished == []

    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert len(finished) == 1
    files, thumb, _dur = finished[0]
    assert files == [{"filename": "a.png", "subfolder": ""}]
    assert thumb is None
    assert job.state == "finished"


def test_completion_generates_thumbnail_when_output_exists(qtbot, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (10, 10), (200, 50, 50)).save(out / "a.png")
    client = _client()
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(out), thumb_dir=tmp_path / "thumbs"))
    job.start()
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append((files, thumb, dur)))

    client.job_completed.emit("comfy-A", SDXL_HISTORY)

    _files, thumb, _dur = finished[0]
    assert thumb is not None
    assert Path(thumb).exists()


class _Later:
    def __init__(self):
        self.waiting = []

    def __call__(self, work, done, *, owner):
        self.waiting.append((work, done))

    def finish_next(self):
        work, done = self.waiting.pop(0)
        done(work())


def _video_job_that_has_rendered(tmp_path, *, run):
    places = OutputPlaces.in_one_folder(tmp_path / "out")
    job = GenerationJob(_client(), JobSpec(I2V, I2V.default_params(), prompt_id="comfy-A"), JobFolders(places=places, thumb_dir=tmp_path / "thumbs"), run=run)
    job.start()
    subfolder = places.run("comfy-A").relative_to(places.comfyui).as_posix() + "/video"
    saved = write_mp4(places.comfyui / subfolder / "wan22_i2v_00001_.mp4")
    return job, saved, {"outputs": {"19": {"images": [{"filename": saved.name,
                                                       "subfolder": subfolder}]}}}


def test_a_video_is_not_complete_until_its_thumbnail_is_ready_to_animate(qtbot, tmp_path):
    later = _Later()
    job, _saved, history = _video_job_that_has_rendered(tmp_path, run=later)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    job._client.job_completed.emit("comfy-A", history)

    assert finished == []
    later.finish_next()
    assert len(finished) == 1
    assert animated_thumbnail_path(tmp_path / "thumbs", "comfy-A").exists()


def test_a_video_making_its_thumbnail_still_reads_as_running_in_the_line(qtbot, tmp_path):
    job, _saved, history = _video_job_that_has_rendered(tmp_path, run=_Later())

    job._client.job_completed.emit("comfy-A", history)

    assert job.state == JobState.FINISHING
    assert display_status(job.state) == JobState.RUNNING


def test_a_video_making_its_thumbnail_on_a_real_thread_finishes_without_holding_the_window(
        qtbot, tmp_path):
    job, _saved, history = _video_job_that_has_rendered(tmp_path, run=run_off_thread)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    job._client.job_completed.emit("comfy-A", history)

    assert finished == []
    qtbot.waitUntil(lambda: bool(finished))


def test_a_video_canceled_while_making_its_thumbnail_stays_where_comfyui_saved_it(qtbot, tmp_path):
    later = _Later()
    job, saved, history = _video_job_that_has_rendered(tmp_path, run=later)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    job._client.job_completed.emit("comfy-A", history)

    job.cancel()
    later.finish_next()

    assert finished == []
    assert job.state == JobState.CANCELED
    assert saved.exists()


def test_a_video_making_its_thumbnail_finishes_once_and_cannot_be_set_aside(qtbot, tmp_path):
    later = _Later()
    job, _saved, history = _video_job_that_has_rendered(tmp_path, run=later)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    job._client.job_completed.emit("comfy-A", history)

    job.reconcile_with(history)
    assert later.waiting[1:] == []
    assert job.defer() is False
    later.finish_next()

    assert len(finished) == 1


def test_a_completion_with_no_output_files_fails_instead(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    finished, failed = [], []
    job.finished.connect(lambda *a: finished.append(a))
    job.failed.connect(failed.append)

    client.job_completed.emit("comfy-A", {"outputs": {}})

    assert finished == [], (
        "taken as finished, it would be an item the app believes in with nothing on disk, "
        "unseen in the gallery")
    assert len(failed) == 1
    assert "without producing an output file" in failed[0]
    assert job.state == "failed"


def test_completion_detaches_so_later_signals_are_ignored(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert len(finished) == 1


def test_reconcile_finishes_a_job_whose_live_completion_was_missed(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))

    job.reconcile_with(SDXL_HISTORY)

    assert finished == [[{"filename": "a.png", "subfolder": ""}]], (
        "ComfyUI says a job is complete once, over its websocket, and a dropped frame or a "
        "reconnect loses it; unread from its history, the job would hang with its output unseen")
    assert job.state == "finished"


def test_reconcile_is_a_noop_while_the_prompt_is_still_running(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    job.reconcile_with({})
    job.reconcile_with(None)

    assert finished == [], (
        "ComfyUI leaves a prompt out of its history until it has run, so an empty fetch is a run still going")
    assert job.state == "queued"


def test_reconcile_does_nothing_once_the_job_has_finished(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert len(finished) == 1

    job.reconcile_with(SDXL_HISTORY)

    assert len(finished) == 1


def test_error_for_our_id_emits_failed(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    failed = []
    job.failed.connect(failed.append)

    client.job_error.emit("comfy-OTHER", "boom")
    assert failed == []

    client.job_error.emit("comfy-A", "boom")
    assert failed == ["boom"]
    assert job.state == "failed"


def test_cancel_dequeues_and_stops_the_prompt_by_name(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.node_executing.emit("comfy-A", "5")
    job.cancel()
    client.cancel_prompt.assert_called_once_with("comfy-A")
    client.interrupt.assert_called_once_with("comfy-A")
    assert job.state == "canceled"


def test_cancel_detaches_from_client(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job.cancel()
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert finished == []


def test_reconnect_attaches_without_submitting(qtbot, tmp_path):
    client = _client()
    job = GenerationJob.reconnect(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="running-id"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    client.submit_job.assert_not_called()
    assert job.prompt_id == "running-id"

    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))
    client.job_completed.emit("running-id", SDXL_HISTORY)
    assert len(finished) == 1


def test_a_job_taken_back_with_no_start_recorded_waits_on_the_server(qtbot, tmp_path):
    job = GenerationJob.reconnect(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="pid"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))

    assert job.state == "queued", (
        "a closing app hands ComfyUI every run still waiting, and most are still queued when it reopens")


def test_a_job_taken_back_that_had_started_is_still_being_made(qtbot, tmp_path):
    job = GenerationJob.reconnect(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="pid"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"), progress_state={"last_progress": [30, 70], "started_at": time.time() - 60})

    assert job.state == "running"


def test_progress_state_snapshots_the_live_progress(qtbot, tmp_path):
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    job = GenerationJob(_client(), JobSpec(wf, {**wf.default_params(), "steps": 20}, prompt_id="pid"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job._on_progress("pid", "15", 10, 10)
    job._on_progress("pid", "16", 3, 10)

    state = job.progress_state()
    assert state["last_progress"] == [526, 810]


def test_a_queued_job_has_no_start_time_yet(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)
    assert job.started_at is None, (
        "a busy queue can hold a job for minutes, and counting that wait as its run "
        "would make the estimate of what is left nonsense")


def test_the_start_time_is_stamped_at_the_first_sign_of_life(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    before = time.time()
    client.progress.emit("comfy-A", "s", 5, 50)
    assert before <= job.started_at <= time.time()

    stamped = job.started_at
    client.progress.emit("comfy-A", "s", 6, 50)
    assert job.started_at == stamped


def test_progress_state_carries_the_start_time(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.progress.emit("comfy-A", "s", 5, 50)
    assert job.progress_state()["started_at"] == job.started_at


def test_reconnect_resumes_the_elapsed_count_from_the_real_start(qtbot, tmp_path):
    began = time.time() - 600
    job = GenerationJob.reconnect(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="pid"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"), progress_state={"last_progress": [30, 70], "started_at": began})
    assert job.started_at == began


def test_a_run_comfyui_starts_before_its_send_returns_keeps_its_real_start(
        qtbot, tmp_path, monkeypatch):
    client = _client()
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    now = [100.0]
    monkeypatch.setattr(generation_job_module, "time", SimpleNamespace(time=lambda: now[0]))

    def send_that_returns_later(payload, prompt_id):
        client.progress.emit(prompt_id, "5", 1, 50)
        now[0] += 5

    client.submit_job.side_effect = send_that_returns_later

    job.start()

    assert job.started_at == 100.0, (
        "the run's clock counts from ComfyUI's first word about it, which can come before the "
        "send has returned")


def test_reconnect_without_a_start_time_stamps_one_at_the_first_tick(qtbot, tmp_path):
    job = GenerationJob.reconnect(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="pid"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    assert job.started_at is None
    job._on_progress("pid", "5", 5, 50)
    assert job.started_at is not None, (
        "a clock that undercounts is better than no clock")


def _reconnected_from_a_snapshot_with_no_pass_count(tmp_path, last_progress, banked):
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    state = {"last_progress": last_progress,
             "tracker": {"total": 818.0, "banked": banked, "stage_max": 10,
                         "stage_seconds": 40.5, "last_value": 3, "node": "16"}}
    return GenerationJob.reconnect(
        _client(), JobSpec(wf, {**wf.default_params(), "steps": 20}, prompt_id="pid"),
        folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path),
                           thumb_dir=tmp_path / "thumbs"),
        progress_state=state)


def test_reconnect_seeds_progress_from_a_persisted_snapshot(qtbot, tmp_path):
    job = _reconnected_from_a_snapshot_with_no_pass_count(tmp_path, [446, 818], banked=405.0)
    assert job.last_progress == (446, 818)
    assert job.last_pass_progress == (3, 10)
    assert job.last_stage == "Second pass"

    job._on_progress("pid", "16", 4, 10)
    assert job.last_progress == (567, 818)


def test_a_first_pass_snapshot_with_no_pass_count_reads_its_pass_from_the_payload(
        qtbot, tmp_path):
    job = _reconnected_from_a_snapshot_with_no_pass_count(tmp_path, [41, 818], banked=0.0)

    assert job.last_pass_progress == (3, 10), (
        "a row written before the pass count was recorded takes it from the run's payload, so its "
        "pass reading comes back with it")


def test_reconnect_without_a_snapshot_starts_blank(qtbot, tmp_path):
    job = GenerationJob.reconnect(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="pid"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    assert job.last_progress == (0, 0)


def test_detach_stops_reacting_without_touching_server(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job._detach()
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert finished == []
    client.interrupt.assert_not_called()
    client.cancel_prompt.assert_not_called()


def test_a_waiting_job_comfyui_says_it_is_making_is_being_made(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)
    started = []
    job.started.connect(lambda: started.append(True))

    job.take_executing(False)
    assert (job.state, started) == ("queued", [])

    job.take_executing(True)
    assert (job.state, started) == ("running", [True]), (
        "a run taken back after it started, with no copy of the app listening, may say nothing more for a "
        "whole sampler step, so ComfyUI's own word for what it is making counts")


def test_take_backlog_holds_another_apps_count_while_the_job_waits(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)

    job.take_backlog(3)

    assert job.foreign_ahead == 3, (
        "ComfyUI serves other apps too, and a wait behind their work, left unexplained, looks like a hang")


def test_a_job_comfyui_has_started_waits_on_nothing(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job.take_backlog(3)

    client.progress.emit("comfy-A", "s", 1, 50)

    assert job.state == "running"
    assert job.foreign_ahead is None
    job.take_backlog(3)
    assert job.foreign_ahead is None


def test_media_type_comes_from_the_workflow_not_a_file(qtbot, tmp_path):
    image = GenerationJob(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail()))
    video = GenerationJob(_client(), JobSpec(WORKFLOW_REGISTRY["wan22_i2v"], WORKFLOW_REGISTRY["wan22_i2v"].default_params()))

    assert (image.media_type, video.media_type) == ("image", "video")


def test_a_job_that_has_not_started_is_not_on_the_server(qtbot, tmp_path):
    client = _client()

    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail()))

    client.submit_job.assert_not_called()
    assert job.state == "idle"


def test_a_job_taken_back_lands_the_run_the_last_copy_had_already_sent(qtbot, tmp_path):
    client = _client()
    client.fetch_history = MagicMock(return_value=SDXL_HISTORY)
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="held-1"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))

    job.start()

    assert finished == [[{"filename": "a.png", "subfolder": ""}]]
    assert job.state == "finished"
    client.submit_job.assert_not_called()


def test_a_job_taken_back_reports_the_run_it_is_finally_given(qtbot, tmp_path):
    client = _client()
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="held-1"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    job.start()
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    client.job_completed.emit("held-1", SDXL_HISTORY)

    assert len(finished) == 1


def test_an_unreachable_queue_leaves_no_stale_count(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)
    job.take_backlog(2)
    assert job.foreign_ahead == 2

    job.take_backlog(None)

    assert job.foreign_ahead is None


def test_defer_stops_the_prompt_and_brings_the_job_back_unsent(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.progress.emit("comfy-A", "5", 3, 10)

    assert job.defer() is True

    assert client.cancel_prompt.call_count == 1, (
        "ComfyUI cannot set a run down and pick it up again, so the run is stopped and thrown away")
    client.cancel_prompt.assert_called_once_with("comfy-A")
    client.interrupt.assert_called_once_with("comfy-A")
    assert job.state == "idle"
    assert job.last_progress == (0, 0), (
        "ComfyUI cannot set a run down and pick it up again, so nothing of the stopped run is kept: it starts over")
    assert job.last_pass_progress is None
    assert job.last_stage == ""
    assert job.started_at is None


def test_defer_detaches_so_the_stopped_runs_end_is_not_taken_as_this_jobs(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job.defer()
    failed = []
    job.failed.connect(lambda *a: failed.append(a))

    client.job_completed.emit("comfy-A", {"outputs": {}})

    assert failed == []
    assert job.state == "idle"


def test_a_job_the_server_does_not_hold_cannot_be_deferred(qtbot, tmp_path):
    client = _client()
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail()))

    assert job.defer() is False

    client.cancel_prompt.assert_not_called()
    client.interrupt.assert_not_called()
    assert job.state == "idle"


def test_a_deferred_job_sent_again_first_forgets_its_false_start(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.fetch_history = MagicMock(return_value={"outputs": {}})
    client.forget_history = MagicMock()
    job.defer()

    job.start()

    client.forget_history.assert_called_once_with("comfy-A")
    assert [c.args[1] for c in client.submit_job.call_args_list] == ["comfy-A", "comfy-A"]
    assert job.state == "queued"


def test_a_job_taken_over_from_another_copy_forgets_its_false_start_when_sent_again(qtbot, tmp_path):
    client = _client()
    job = GenerationJob.reconnect(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="comfy-A"), folders=JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))
    client.fetch_history = MagicMock(return_value={"outputs": {}})
    job.defer()

    job.start()

    client.forget_history.assert_called_once_with("comfy-A")
    client.submit_job.assert_called_once_with(job.payload, "comfy-A")


def test_a_deferred_job_whose_run_finished_after_all_lands_instead_of_running_again(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.fetch_history = MagicMock(return_value=SDXL_HISTORY)
    client.forget_history = MagicMock()
    job.defer()
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))

    job.start()

    assert finished == [[{"filename": "a.png", "subfolder": ""}]]
    assert job.state == "finished"
    client.submit_job.assert_called_once()
    client.forget_history.assert_not_called()


def test_a_first_send_forgets_nothing_on_a_server_with_no_record_of_it(qtbot, tmp_path):
    client = _client()
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail()))

    job.start()

    client.forget_history.assert_not_called()
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)


def test_a_row_waiting_to_be_sent_is_called_queued_on_screen():
    assert display_status(GenerationStatus.PENDING) == JobState.QUEUED
    assert display_status(GenerationStatus.RUNNING) == JobState.RUNNING


def test_a_job_waiting_here_or_on_the_server_is_called_queued_on_screen():
    assert display_status(JobState.IDLE) == JobState.QUEUED
    assert display_status(JobState.QUEUED) == JobState.QUEUED
    assert display_status(JobState.RUNNING) == JobState.RUNNING
    assert display_status(JobState.SPEAKING) == JobState.SPEAKING


def test_every_state_a_job_walks_through_is_named_once():
    assert {state.value for state in JobState} == {
        "idle", "speaking", "queued", "running", "finishing", "finished", "failed", "canceled"}


def test_a_row_inserted_for_a_job_has_the_source_the_job_carries(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    job = GenerationJob(_client(), JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), source="experiment"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))

    insert_generation_row(db, job)

    assert job.source == "experiment"
    assert db.get_generation(job.prompt_id)["source"] == "experiment"


def test_a_server_that_cannot_be_asked_after_the_stopped_run_is_taken_to_hold_nothing(qtbot, tmp_path):
    client = _client()
    client.fetch_history.side_effect = OSError("ComfyUI is down")
    job = GenerationJob(client, JobSpec(SDXL, _params_with_the_two_sampler_enhance_tail(), prompt_id="comfy-A"), JobFolders(places=OutputPlaces.in_one_folder(tmp_path), thumb_dir=tmp_path / "thumbs"))

    job.start()

    client.submit_job.assert_called_once_with(job.payload, "comfy-A")
    client.forget_history.assert_not_called()
    assert job.state == "queued"
