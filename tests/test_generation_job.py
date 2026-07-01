from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generation_job import GenerationJob, persist_generation
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
    return dict(SDXL.default_params())


def _started_job(tmp_path):
    client = _client()
    job = GenerationJob(
        client, SDXL, _params(),
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    job.start()
    return job, client


def test_persist_generation_saves_a_completed_row_with_its_outputs(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    job = GenerationJob(_client(), SDXL, dict(_params(), positive_prompt="a cat", seed=9))
    files = [{"filename": "a.png", "subfolder": "image"}]

    persist_generation(db, job, files, thumb_path="/thumbs/a.jpg", duration=12.5)

    row = db.get_generation(job.prompt_id)
    assert row["status"] == "completed"
    assert row["workflow_name"] == "sdxl_t2i"
    assert "a.png" in row["output_files"]
    assert row["seed"] == 9
    assert row["duration_seconds"] == 12.5


def test_start_submits_payload_and_queues(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    client.submit_job.assert_called_once_with(job.payload)
    assert job.comfy_id == "comfy-A"
    assert job.state == "queued"


def test_progress_for_our_id_marks_started_and_forwards(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    started, progress = [], []
    job.started.connect(lambda: started.append(True))
    job.progress.connect(lambda v, m: progress.append((v, m)))

    client.progress.emit("comfy-OTHER", 5, 50)
    assert started == [] and progress == []

    # SDXL is a single 50-step pass, so progress forwards as value-over-total.
    client.progress.emit("comfy-A", 5, 50)
    assert started == [True]
    assert progress == [(5, 50)]
    assert job.state == "running"
    assert job.last_progress == (5, 50)

    client.progress.emit("comfy-A", 7, 50)
    assert started == [True]  # started fires only once


def test_progress_accumulates_across_sampler_stages(qtbot, tmp_path):
    # A dual-noise video job samples in two passes. ComfyUI counts each pass from
    # its own zero, so the job must accumulate them into one 0-to-total ramp
    # rather than forward a bar that resets halfway through.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    client = _client()
    job = GenerationJob(
        client, wf, {**wf.default_params(), "steps": 20},
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    job.start()
    seen = []
    job.progress.connect(lambda v, m: seen.append((v, m)))

    client.progress.emit("comfy-A", 10, 10)  # first pass finishes (10 of 20)
    client.progress.emit("comfy-A", 1, 10)   # second pass restarts its own count

    assert seen == [(10, 20), (11, 20)]       # continues past the halfway mark
    assert job.last_progress == (11, 20)


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
    job.start()
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append((files, thumb, dur)))

    client.job_completed.emit("comfy-A", SDXL_HISTORY)

    _files, thumb, _dur = finished[0]
    assert thumb is not None and Path(thumb).exists()


def test_completion_detaches_so_later_signals_are_ignored(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert len(finished) == 1


def test_reconcile_finishes_a_job_whose_live_completion_was_missed(qtbot, tmp_path):
    # The websocket completion is a one-shot; if it never arrives, reconcile()
    # pulls /history as a backstop and finishes the job just as the signal would.
    job, client = _started_job(tmp_path)
    client.fetch_history = MagicMock(return_value=SDXL_HISTORY)
    finished = []
    job.finished.connect(lambda files, thumb, dur: finished.append(files))

    job.reconcile()  # no job_completed was ever emitted

    client.fetch_history.assert_called_once_with("comfy-A")
    assert finished == [[{"filename": "a.png", "subfolder": ""}]]
    assert job.state == "finished"


def test_reconcile_is_a_noop_while_the_prompt_is_still_running(qtbot, tmp_path):
    # A queued/running prompt isn't in /history yet, so reconcile leaves it be.
    job, client = _started_job(tmp_path)
    client.fetch_history = MagicMock(return_value={})
    finished = []
    job.finished.connect(lambda *a: finished.append(a))

    job.reconcile()

    assert finished == []
    assert job.state == "queued"


def test_reconcile_does_nothing_once_the_job_has_finished(qtbot, tmp_path):
    # After the live signal completed it, the backstop must not re-fire or re-fetch.
    job, client = _started_job(tmp_path)
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert len(finished) == 1

    client.fetch_history = MagicMock(return_value=SDXL_HISTORY)
    job.reconcile()

    assert len(finished) == 1
    client.fetch_history.assert_not_called()


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


def test_detach_stops_reacting_without_touching_server(qtbot, tmp_path):
    job, client = _started_job(tmp_path)
    job.detach()
    finished = []
    job.finished.connect(lambda *a: finished.append(a))
    client.job_completed.emit("comfy-A", SDXL_HISTORY)
    assert finished == []
    client.interrupt.assert_not_called()
    client.cancel_prompt.assert_not_called()
