"""A job whose story has lines speaks them before it is sent."""

from unittest.mock import MagicMock

from origenerator.comfyui_client import ComfyUIClient
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
