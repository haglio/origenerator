from __future__ import annotations

import functools
import subprocess
import sys
import threading
import urllib.error
from unittest.mock import MagicMock

from PyQt6.QtCore import QTimer

from origenerator.comfyui_client import ComfyUIClient
from origenerator.gui import generation_job, job_speaker
from origenerator.gui.generation_job import GenerationJob, JobFolders, JobSpec
from origenerator.speech import scene_speech
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.children import HANG_AFTER_S
from tests.comfyui_folders import SUITE_FOLDERS

I2V = WORKFLOW_REGISTRY["wan22_i2v"]
_HANG_MS = HANG_AFTER_S * 1000


class _Speaker:
    def __init__(self):
        self.asked = []

    def speak(self, params, done, failed):
        self.asked.append((params, done, failed))

    def speak_here(self, params):
        self.asked.append((params, None, None))


def _from_a_window(post):
    post()


def _client():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-A")
    client.free_memory = MagicMock()
    client.fetch_history = MagicMock(return_value={})
    return client


def _spoken_params():
    return dict(I2V.default_params(), frame_count=161, scene_frames=[161], scene_lines=["Come in."])


def test_a_story_with_lines_is_spoken_before_it_is_submitted(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path), speaker=speaker)
    job.start(_from_a_window)
    assert job.state == "speaking"
    client.submit_job.assert_not_called()
    (params, done, _failed), = speaker.asked
    assert params["scene_lines"] == ["Come in."]
    done()
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)
    assert job.state == "queued"


def test_started_with_no_window_to_answer_its_voice_a_story_is_spoken_there_then_sent(
        qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path), speaker=speaker)
    job.start()
    (params, done, _failed), = speaker.asked
    assert params["scene_lines"] == ["Come in."]
    assert done is None
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)
    assert job.state == "queued"


def test_lines_already_spoken_send_the_job_at_once(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    params = _spoken_params()
    file = tmp_path / scene_speech(params)[0].file
    file.parent.mkdir(parents=True)
    file.write_bytes(b"RIFF")
    job = GenerationJob(client, JobSpec(I2V, params), JobFolders(input_dir=tmp_path), speaker=speaker)
    job.start()
    assert speaker.asked == []
    client.submit_job.assert_called_once()
    assert job.state == "queued"


def test_a_story_without_lines_never_calls_the_voice(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, JobSpec(I2V, dict(I2V.default_params(), frame_count=81)), JobFolders(input_dir=tmp_path), speaker=speaker)
    job.start()
    assert speaker.asked == []
    client.submit_job.assert_called_once()


def test_a_voice_that_fails_fails_the_job_before_comfyui_hears_of_it(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path), speaker=speaker)
    failed = []
    job.failed.connect(failed.append)
    job.start(_from_a_window)
    (_params, _done, fail), = speaker.asked
    fail("No voice is set up")
    assert failed == ["No voice is set up"]
    assert job.state == "failed"
    client.submit_job.assert_not_called()


def test_a_story_spoken_while_comfyui_is_down_says_so_and_can_be_sent_again(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    client.submit_job = MagicMock(side_effect=[urllib.error.URLError(ConnectionRefusedError(
        10061, "No connection could be made because the target machine actively refused it")),
        "comfy-A"])
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path), speaker=speaker)
    said = []
    job.unreachable.connect(said.append)
    job.failed.connect(said.append)
    job.start(_from_a_window)
    (params, done, _failed), = speaker.asked

    _spoken_file(params, tmp_path)
    done()
    assert len(said) == 1
    assert "10061" in said[0]
    job.start(_from_a_window)

    assert job.state == "queued"
    assert client.submit_job.call_count == 2


def test_a_job_canceled_while_its_lines_are_spoken_is_not_sent(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path), speaker=speaker)
    job.start(_from_a_window)
    job.cancel()
    (_params, done, _failed), = speaker.asked
    done()
    client.submit_job.assert_not_called()
    assert job.state == "canceled"



def _spoken_file(params, input_dir):
    path = input_dir / scene_speech(params)[0].file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")
    return [path]


def test_the_voice_speaks_off_the_gui_thread_and_the_job_is_sent_from_it(qtbot, tmp_path, monkeypatch):
    seen = {}
    gui_thread = threading.get_ident()
    done_speaking = threading.Event()

    def speaks_until_told(params, *, input_dir, python, **kwargs):
        seen["spoke_on"] = threading.get_ident()
        assert done_speaking.wait(HANG_AFTER_S), "the test never let the voice finish"
        return _spoken_file(params, input_dir)

    monkeypatch.setattr(generation_job.speech, "ensure_speech_files", speaks_until_told)
    monkeypatch.setattr(job_speaker, "COMFYUI_INPUT_DIR", tmp_path)
    client = _client()
    client.submit_job = MagicMock(side_effect=lambda *a: seen.setdefault("sent_on", threading.get_ident()))
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(20)
    job.start(_from_a_window)
    assert job.state == "speaking"
    qtbot.waitUntil(lambda: "spoke_on" in seen and len(ticks) >= 5, timeout=_HANG_MS)
    done_speaking.set()
    qtbot.waitUntil(lambda: job.state == "queued", timeout=_HANG_MS)
    timer.stop()
    assert client.free_memory.call_count == 1, (
        "the models ComfyUI keeps loaded would leave the voice no room on the graphics card")
    assert seen["spoke_on"] != gui_thread
    assert seen["sent_on"] == gui_thread


def test_the_voice_a_job_with_no_window_asks_for_speaks_on_the_starting_thread(
        qtbot, tmp_path, monkeypatch):
    spoke_on = []

    def speak(params, *, input_dir, python, **kwargs):
        spoke_on.append(threading.get_ident())
        return _spoken_file(params, input_dir)

    monkeypatch.setattr(generation_job.speech, "ensure_speech_files", speak)
    monkeypatch.setattr(job_speaker, "COMFYUI_INPUT_DIR", tmp_path)
    client = _client()
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path))
    job.start()
    assert spoke_on == [threading.get_ident()]
    client.free_memory.assert_called_once()
    client.submit_job.assert_called_once()
    assert job.state == "queued"


def _at_normal_priority(args, **kwargs):
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.NORMAL_PRIORITY_CLASS
    return subprocess.run(args, check=False, **kwargs)


def test_the_voice_runs_as_a_real_process_without_holding_the_window(qtbot, tmp_path, monkeypatch):
    go = tmp_path / "go"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys, time, pathlib\n"
        f"go, give_up = pathlib.Path({str(go)!r}), time.monotonic() + {HANG_AFTER_S}\n"
        "while not go.exists():\n"
        "    if time.monotonic() > give_up: sys.exit('the test never let the voice finish')\n"
        "    time.sleep(0.02)\n"
        "for item in json.load(open(sys.argv[1]))['items']:\n"
        "    pathlib.Path(item['out']).write_bytes(b'RIFF')\n",
        encoding="utf-8")
    monkeypatch.setattr(generation_job.speech, "WORKER", worker)
    monkeypatch.setattr(generation_job.speech, "ensure_speech_files",
                        functools.partial(generation_job.speech.ensure_speech_files, run=_at_normal_priority))
    monkeypatch.setattr(job_speaker, "COMFYUI_INPUT_DIR", tmp_path)
    monkeypatch.setattr(job_speaker, "SPEECH_PYTHON", sys.executable)
    client = _client()
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(20)
    job.start(_from_a_window)
    qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=_HANG_MS)
    assert job.state == "speaking"
    go.write_bytes(b"")
    qtbot.waitUntil(lambda: job.state == "queued", timeout=_HANG_MS)
    timer.stop()
    client.submit_job.assert_called_once()
    assert (tmp_path / scene_speech(_spoken_params())[0].file).exists()


def test_a_comfyui_that_keeps_its_models_still_gets_the_lines_spoken():
    spoken = []
    client = _client()

    def keeps_its_models():
        raise OSError("ComfyUI is busy")

    client.free_memory = keeps_its_models

    job_speaker.Speaker(client, lines_on_disk=spoken.append).speak_here({"made-up": "params"})

    assert spoken == [{"made-up": "params"}]


def test_a_voice_that_cannot_speak_answers_with_its_reason(qtbot):
    def breaks(_params):
        raise RuntimeError("the voice broke")

    answers = []

    speaker = job_speaker.Speaker(_client(), lines_on_disk=breaks)
    speaker.speak({}, lambda: answers.append("done"), answers.append)
    qtbot.waitUntil(lambda: bool(answers), timeout=5000)

    assert answers == ["the voice broke"]


def test_a_refused_send_after_speaking_fails_the_job(qtbot, tmp_path):
    client, speaker = _client(), _Speaker()
    client.submit_job = MagicMock(side_effect=RuntimeError("the graph was refused"))
    job = GenerationJob(client, JobSpec(I2V, _spoken_params()), JobFolders(input_dir=tmp_path), speaker=speaker)
    failed = []
    job.failed.connect(failed.append)
    job.start(_from_a_window)
    (params, done, _failed), = speaker.asked
    _spoken_file(params, tmp_path)

    done()

    assert failed == ["the graph was refused"], (
        "the send is made when the voice is done, with no caller above it to raise to, so a refusal "
        "fails the job the way a run that errors does")
    assert job.state == "failed"
