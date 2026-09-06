"""A job whose story has lines speaks them before it is sent."""

import sys
import threading
import time
from unittest.mock import MagicMock

from PyQt6.QtCore import QTimer

from origenerator.comfyui_client import ComfyUIClient
from origenerator.gui import generation_job
from origenerator.gui.generation_job import GenerationJob
from origenerator.speech import scene_speech
from origenerator.workflows import WORKFLOW_REGISTRY

I2V = WORKFLOW_REGISTRY["wan22_i2v"]


class _Speaker:
    """Records what it was asked to speak; the test answers when it likes."""

    def __init__(self):
        self.asked = []

    def speak(self, params, done, failed):
        self.asked.append((params, done, failed))


def _client():
    client = ComfyUIClient()
    client.submit_job = MagicMock(return_value="comfy-A")
    client.free_memory = MagicMock()
    return client


def _spoken_params():
    return dict(I2V.default_params(), frame_count=161, scene_frames=[161], scene_lines=["Come in."])


def test_a_story_with_lines_is_spoken_before_it_is_submitted(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, I2V, _spoken_params(), input_dir=tmp_path, speaker=speaker)
    job.start()
    assert job.state == "speaking"
    client.submit_job.assert_not_called()
    (params, done, _failed), = speaker.asked
    assert params["scene_lines"] == ["Come in."]
    done()
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)
    assert job.state == "queued"


def test_lines_already_spoken_send_the_job_at_once(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    params = _spoken_params()
    file = tmp_path / scene_speech(params)[0].file
    file.parent.mkdir(parents=True)
    file.write_bytes(b"RIFF")
    job = GenerationJob(client, I2V, params, input_dir=tmp_path, speaker=speaker)
    job.start()
    assert speaker.asked == []
    client.submit_job.assert_called_once()
    assert job.state == "queued"


def test_a_story_without_lines_never_calls_the_voice(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, I2V, dict(I2V.default_params(), frame_count=81),
                        input_dir=tmp_path, speaker=speaker)
    job.start()
    assert speaker.asked == []
    client.submit_job.assert_called_once()


def test_a_voice_that_fails_fails_the_job_before_comfyui_hears_of_it(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, I2V, _spoken_params(), input_dir=tmp_path, speaker=speaker)
    failed = []
    job.failed.connect(failed.append)
    job.start()
    (_params, _done, fail), = speaker.asked
    fail("No voice is set up")
    assert failed == ["No voice is set up"]
    assert job.state == "failed"
    client.submit_job.assert_not_called()


def test_a_job_canceled_while_its_lines_are_spoken_is_not_sent(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, I2V, _spoken_params(), input_dir=tmp_path, speaker=speaker)
    job.start()
    job.cancel()
    (_params, done, _failed), = speaker.asked
    done()
    client.submit_job.assert_not_called()
    assert job.state == "canceled"


# ---- the voice at work, off the GUI thread ---------------------------------------


def _spoken_file(params, input_dir):
    path = input_dir / scene_speech(params)[0].file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")
    return [path]


def test_the_voice_speaks_off_the_gui_thread_and_the_job_is_sent_from_it(qtbot, tmp_path, monkeypatch):
    # The real speaker: a thread does the speaking (here a half-second stand-in)
    # while the window keeps its events flowing, and the submit that follows
    # happens back on the GUI thread, where every job's signals are wired.
    seen = {}
    gui_thread = threading.get_ident()

    def slow_speak(params, *, input_dir, python, **kwargs):
        seen["spoke_on"] = threading.get_ident()
        time.sleep(0.5)
        return _spoken_file(params, input_dir)

    monkeypatch.setattr(generation_job.speech, "ensure_speech_files", slow_speak)
    monkeypatch.setattr(generation_job, "COMFYUI_INPUT_DIR", tmp_path)
    client = _client()
    client.submit_job = MagicMock(side_effect=lambda *a: seen.setdefault("sent_on", threading.get_ident()))
    job = GenerationJob(client, I2V, _spoken_params(), input_dir=tmp_path)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(20)
    started = time.monotonic()
    job.start()
    assert time.monotonic() - started < 0.25, "start() waited on the voice"
    assert job.state == "speaking"
    qtbot.waitUntil(lambda: job.state == "queued", timeout=5000)
    timer.stop()
    client.free_memory.assert_called_once()
    assert seen["spoke_on"] != gui_thread
    assert seen["sent_on"] == gui_thread
    assert len(ticks) >= 5, "the window's events stopped while the voice spoke"


def test_the_voice_runs_as_a_real_process_without_holding_the_window(qtbot, tmp_path, monkeypatch):
    # The worker is a process the thread waits on; a stand-in worker here
    # sleeps and writes the files the job asks for, the way the real one does.
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys, time, pathlib\n"
        "time.sleep(0.6)\n"
        "for item in json.load(open(sys.argv[1]))['items']:\n"
        "    pathlib.Path(item['out']).write_bytes(b'RIFF')\n",
        encoding="utf-8")
    monkeypatch.setattr(generation_job.speech, "WORKER", worker)
    monkeypatch.setattr(generation_job, "COMFYUI_INPUT_DIR", tmp_path)
    monkeypatch.setattr(generation_job, "SPEECH_PYTHON", sys.executable)
    client = _client()
    job = GenerationJob(client, I2V, _spoken_params(), input_dir=tmp_path)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(20)
    job.start()
    qtbot.waitUntil(lambda: job.state == "queued", timeout=10000)
    timer.stop()
    client.submit_job.assert_called_once()
    assert (tmp_path / scene_speech(_spoken_params())[0].file).exists()
    assert len(ticks) >= 5, "the window's events stopped while the voice spoke"
