import time
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from origenerator.comfyui_client import ComfyUIClient
from origenerator.gui.generation_job import GenerationJob
from origenerator.workflows import WORKFLOW_REGISTRY

SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]
SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


def _client():
    client = ComfyUIClient()
    client.submit_job = MagicMock(return_value="comfy-A")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    return client


def _params():
    # enhance on, so the payload carries the two-sampler shape these tests pin
    # the whole-run step total against. Nothing turns it on by hand in the app
    # any more (the gallery's Enhance subpanel applies enhancement as a layer),
    # but a reused old run still rebuilds exactly this graph.
    return dict(SDXL.default_params(), enhance=True)


def _started_job(tmp_path):
    client = _client()
    job = GenerationJob(
        client, SDXL, _params(),
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    job.prompt_id = "comfy-A"  # pin our id so the client-signal emits below match
    job.start()
    return job, client


def test_start_submits_payload_under_our_prompt_id_and_queues(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    # We submit under our own prompt_id, so ComfyUI's signals key on the same id.
    client.submit_job.assert_called_once_with(job.payload, "comfy-A")
    assert job.state == "queued"


def test_progress_for_our_id_marks_started_and_forwards(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    started, progress = [], []
    job.started.connect(lambda: started.append(True))
    job.progress.connect(lambda v, m: progress.append((v, m)))

    client.progress.emit("comfy-OTHER", 5, 50)
    assert started == [] and progress == []

    # SDXL runs a 50-step base pass then a 20-step enhance pass, so progress
    # forwards as value over the 70-step whole-run total.
    client.progress.emit("comfy-A", 5, 50)
    assert started == [True]
    assert progress == [(5, 70)]
    assert job.state == "running"
    assert job.last_progress == (5, 70)

    client.progress.emit("comfy-A", 7, 50)
    assert started == [True]  # started fires only once


def test_progress_accumulates_across_sampler_stages(qtbot, tmp_path):
    # A dual-noise video job samples in two passes, then scores itself in a third
    # — 20 video steps and 50 of audio. ComfyUI counts each pass from its own
    # zero, so the job must accumulate them into one 0-to-total ramp rather than
    # forward a bar that resets partway through.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    client = _client()
    job = GenerationJob(
        client, wf, {**wf.default_params(), "steps": 20},
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    job.prompt_id = "comfy-A"
    job.start()
    seen = []
    job.progress.connect(lambda v, m: seen.append((v, m)))

    client.progress.emit("comfy-A", 10, 10)  # first pass finishes (10 of 70)
    client.progress.emit("comfy-A", 1, 10)   # second pass restarts its own count

    assert seen == [(10, 70), (11, 70)]       # continues past the first pass's end
    assert job.last_progress == (11, 70)


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
    assert thumb is None  # a.png is not on disk, so no thumbnail
    assert job.state == "finished"


def test_completion_generates_thumbnail_when_output_exists(qtbot, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (10, 10), (200, 50, 50)).save(out / "a.png")
    client = _client()
    job = GenerationJob(client, SDXL, _params(), output_dir=out, thumb_dir=tmp_path / "thumbs")
    job.prompt_id = "comfy-A"
    job.start()
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append((files, thumb, dur)))

    client.job_completed.emit("comfy-A", SDXL_HISTORY)

    _files, thumb, _dur = finished[0]
    assert thumb is not None and Path(thumb).exists()


def test_a_completion_with_no_output_files_fails_instead(qtbot, tmp_path):
    # ComfyUI ends an interrupted prompt exactly as it ends a finished one, and
    # its history then carries no outputs. Such a run made no file, so it must not
    # be recorded as a completed generation — one that is blocks a re-run of the
    # same settings as a duplicate of something that doesn't exist.
    job, client = _started_job(tmp_path)
    finished, failed = [], []
    job.finished.connect(lambda *a: finished.append(a))
    job.failed.connect(failed.append)

    client.job_completed.emit("comfy-A", {"outputs": {}})

    assert finished == []
    assert len(failed) == 1 and "without producing an output file" in failed[0]
    assert job.state == "failed"


def test_completion_detaches_so_later_signals_are_ignored(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert len(finished) == 1


def test_reconcile_finishes_a_job_whose_live_completion_was_missed(qtbot, tmp_path):
    # The websocket completion is a one-shot; if it never arrives, the poll
    # fetches /history as a backstop and this applies it, finishing the job
    # just as the signal would have.
    job, _client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))

    job.reconcile_with(SDXL_HISTORY)  # no job_completed was ever emitted

    assert finished == [[{"filename": "a.png", "subfolder": ""}]]
    assert job.state == "finished"


def test_reconcile_is_a_noop_while_the_prompt_is_still_running(qtbot, tmp_path):
    # A queued/running prompt isn't in /history yet, so its fetch comes back
    # empty — and a tick that fetched nothing at all applies None.
    job, _client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    job.reconcile_with({})
    job.reconcile_with(None)

    assert finished == []
    assert job.state == "queued"


def test_reconcile_does_nothing_once_the_job_has_finished(qtbot, tmp_path):
    # After the live signal completed it, the backstop must not re-fire.
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


def test_cancel_while_running_interrupts(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.node_executing.emit("comfy-A", "5")  # job is now executing
    job.cancel()
    client.interrupt.assert_called_once()
    client.cancel_prompt.assert_not_called()
    assert job.state == "canceled"


def test_cancel_while_queued_dequeues(qtbot, tmp_path):
    job, client = _started_job(tmp_path)  # still queued, not executing
    job.cancel()
    client.cancel_prompt.assert_called_once_with("comfy-A")
    client.interrupt.assert_not_called()
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
    job = GenerationJob.reconnect(
        client, SDXL, _params(), "running-id",
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    client.submit_job.assert_not_called()  # already on the server; don't resubmit
    assert job.prompt_id == "running-id"
    assert job.state == "running"

    # Live signals for that id now flow through, ending in a normal completion.
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))
    client.job_completed.emit("running-id", SDXL_HISTORY)
    assert len(finished) == 1


def test_progress_state_snapshots_the_live_progress(qtbot, tmp_path):
    # What gets persisted on the running row: a JSON-able snapshot of where the ramp
    # is, so a restart can resume it.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    job = GenerationJob(_client(), wf, {**wf.default_params(), "steps": 20},
                        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs")
    job.prompt_id = "pid"
    job._on_progress("pid", 10, 10)   # first pass done
    job._on_progress("pid", 3, 10)    # second pass at 3 -> 13 of the run's 70

    state = job.progress_state()
    assert state["last_progress"] == [13, 70]


def test_a_queued_job_has_no_start_time_yet(qtbot, tmp_path):
    # Submitted isn't started: on a busy queue the wait can be many minutes, and
    # counting it as run time would make the estimate of what's left nonsense.
    job, _client_ = _started_job(tmp_path)
    assert job.started_at is None


def test_the_start_time_is_stamped_at_the_first_sign_of_life(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    before = time.time()
    client.progress.emit("comfy-A", 5, 50)
    assert before <= job.started_at <= time.time()

    stamped = job.started_at
    client.progress.emit("comfy-A", 6, 50)
    assert job.started_at == stamped  # the run began once, not on every tick


def test_progress_state_carries_the_start_time(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.progress.emit("comfy-A", 5, 50)
    assert job.progress_state()["started_at"] == job.started_at


def test_reconnect_resumes_the_elapsed_count_from_the_real_start(qtbot, tmp_path):
    # The payoff for persisting it: an app restarted mid-run picks the count back
    # up where the run really began, rather than restarting the clock at zero and
    # claiming a job ten minutes in has only just started.
    began = time.time() - 600
    job = GenerationJob.reconnect(
        _client(), SDXL, _params(), "pid",
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
        progress_state={"last_progress": [30, 70], "started_at": began},
    )
    assert job.started_at == began


def test_reconnect_without_a_start_time_stamps_one_at_the_first_tick(qtbot, tmp_path):
    # A row persisted before the start time was recorded arrives already running,
    # so the queued->running flip that normally stamps it never happens. It gets
    # one anyway — an undercount beats a job that never shows a clock at all.
    job = GenerationJob.reconnect(
        _client(), SDXL, _params(), "pid",
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    assert job.started_at is None
    job._on_progress("pid", 5, 50)
    assert job.started_at is not None


def test_reconnect_seeds_progress_from_a_persisted_snapshot(qtbot, tmp_path):
    # The payoff: a reconnected job shows its last position at once, and the restored
    # tracker carries the multi-pass ramp forward rather than restarting from the
    # pass it reconnects into.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    state = {"last_progress": [13, 20],
             "tracker": {"total": 20, "banked": 10, "stage_max": 10, "last_value": 3}}
    job = GenerationJob.reconnect(
        _client(), wf, {**wf.default_params(), "steps": 20}, "pid",
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs", progress_state=state,
    )
    assert job.last_progress == (13, 20)     # bar resumes at its last spot immediately

    job._on_progress("pid", 4, 10)           # next real tick from ComfyUI
    assert job.last_progress == (14, 20)     # carries on, not back to 4/20


def test_reconnect_without_a_snapshot_starts_blank(qtbot, tmp_path):
    job = GenerationJob.reconnect(
        _client(), SDXL, _params(), "pid",
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    assert job.last_progress == (0, 0)  # nothing persisted yet -> indeterminate, as before


def test_detach_stops_reacting_without_touching_server(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job._detach()
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert finished == []
    client.interrupt.assert_not_called()
    client.cancel_prompt.assert_not_called()


# --- what another app is holding ComfyUI with, ahead of a job it hasn't started

def test_take_backlog_holds_another_apps_count_while_the_job_waits(qtbot, tmp_path):
    job, _client = _started_job(tmp_path)

    job.take_backlog(3)

    assert job.foreign_ahead == 3


def test_a_job_comfyui_has_started_waits_on_nothing(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job.take_backlog(3)

    client.progress.emit("comfy-A", 1, 50)  # ComfyUI picked it up

    assert job.state == "running"
    assert job.foreign_ahead is None  # the count clears the moment it's ours
    job.take_backlog(3)  # a count fetched for a job no longer queued is dropped
    assert job.foreign_ahead is None


# --- what the queue needs of a job it has not sent yet -----------------------

def test_media_type_comes_from_the_workflow_not_a_file(qtbot, tmp_path):
    # The queue places a job before it has run, so what it will produce has to be
    # readable from the recipe alone.
    image = GenerationJob(_client(), SDXL, _params())
    video = GenerationJob(_client(), WORKFLOW_REGISTRY["wan22_i2v"],
                          WORKFLOW_REGISTRY["wan22_i2v"].default_params())

    assert (image.media_type, video.media_type) == ("image", "video")


def test_an_undeclared_workflow_counts_as_an_image(qtbot, tmp_path):
    # Images go first and start sooner, so an unfamiliar one being made promptly
    # is the harmless way to be wrong; treating it as a video could hold it back
    # through a whole slideshow.
    job = GenerationJob(_client(), SDXL, _params())
    job.workflow = MagicMock(spec=[])  # a workflow declaring no output type

    assert job.media_type == "image"


def test_a_job_that_has_not_started_is_not_on_the_server(qtbot, tmp_path):
    # A built job is only a job this app is holding: nothing was submitted, so
    # the queue is free to re-order it, gate it, or drop it.
    client = _client()

    job = GenerationJob(client, SDXL, _params())

    client.submit_job.assert_not_called()
    assert job.state == "idle"


def test_readopt_comes_back_unsent_under_the_rows_prompt_id(qtbot, tmp_path):
    # The counterpart to reconnect, for a row the queue was still holding when the
    # app closed: the server has never heard of it, so there is nothing to rebind
    # to and everything to re-send when its turn comes.
    client = _client()

    job = GenerationJob.readopt(client, SDXL, _params(), "held-1")

    assert (job.prompt_id, job.state) == ("held-1", "idle")
    client.submit_job.assert_not_called()

    job.start()
    client.submit_job.assert_called_once_with(job.payload, "held-1")


def test_a_re_adopted_job_reports_the_run_it_is_finally_given(qtbot, tmp_path):
    # It has to listen on the same id its row carries, or the run it eventually
    # gets would finish invisibly.
    client = _client()
    job = GenerationJob.readopt(
        client, SDXL, _params(), "held-1",
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    job.start()
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    client.job_completed.emit("held-1", SDXL_HISTORY)

    assert len(finished) == 1


def test_an_unreachable_queue_leaves_no_stale_count(qtbot, tmp_path):
    # A count that outlived the read behind it would be a worse lie than none:
    # a failed fetch arrives as None, and None replaces what was showing.
    job, _client = _started_job(tmp_path)
    job.take_backlog(2)
    assert job.foreign_ahead == 2

    job.take_backlog(None)

    assert job.foreign_ahead is None
