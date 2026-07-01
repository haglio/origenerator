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
    return dict(SDXL.default_params())


def _started_job(tmp_path):
    client = _client()
    job = GenerationJob(
        client, SDXL, _params(),
        output_dir=tmp_path, thumb_dir=tmp_path / "thumbs",
    )
    job.start()
    return job, client


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

    client.progress.emit("comfy-OTHER", 5, 10)
    assert started == [] and progress == []

    client.progress.emit("comfy-A", 5, 10)
    assert started == [True]
    assert progress == [(5, 10)]
    assert job.state == "running"
    assert job.last_progress == (5, 10)

    client.progress.emit("comfy-A", 7, 10)
    assert started == [True]  # started fires only once


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
