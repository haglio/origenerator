"""Her lines, spoken: which files a story's scenes need and how they are made."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from origenerator import speech
from origenerator.speech import SPEECH_DIR, SpeechError, scene_speech, voice_request
from tools import speech_worker


def _params(**overrides):
    return {"frame_count": 81, "scene_frames": [81], "scene_lines": [""],
            "audio_seed": 7, "voice": "Vivian", "voice_sample": "", "voice_sample_text": "",
            **overrides}


# ---- what each scene says ----------------------------------------------------


def test_a_scene_with_no_line_says_nothing():
    assert scene_speech(_params()) == [None]
    assert scene_speech(_params(scene_lines=["   "])) == [None]


def test_a_workflow_without_lines_has_no_scenes_to_speak():
    # A still's recipe carries no scene_lines (nor a frame count to read them
    # against), and it is simply a recipe nothing in it speaks.
    assert scene_speech({"positive_prompt": "a still", "seed": 1}) == []
    assert speech.missing_speech({"positive_prompt": "a still"}, Path("nowhere")) == []


def test_each_scene_speaks_its_own_line_for_its_own_seconds():
    spoken = scene_speech(_params(frame_count=401, scene_frames=[161, 81, 161],
                                  scene_lines=[" Come in. ", "", "Sit."]))
    assert spoken[1] is None
    assert (spoken[0].text, spoken[0].frames, spoken[0].seconds) == ("Come in.", 161, pytest.approx(161 / 16))
    assert (spoken[2].text, spoken[2].frames) == ("Sit.", 161)
    assert spoken[0].file.startswith(SPEECH_DIR + "/") and spoken[0].file.endswith(".wav")


def test_a_lone_scene_speaks_for_the_clip_length_whatever_its_own_entry_says():
    # The graph runs a lone scene for the clip length (scene_plan), so its
    # line lasts that long too.
    spoken = scene_speech(_params(frame_count=121, scene_frames=[81], scene_lines=["hi"]))
    assert spoken[0].frames == 121


def test_a_lines_file_is_named_from_everything_that_shapes_it():
    base = scene_speech(_params(scene_lines=["hi"]))[0].file
    assert scene_speech(_params(scene_lines=["hi"]))[0].file == base
    assert scene_speech(_params(scene_lines=["hi there"]))[0].file != base
    assert scene_speech(_params(scene_lines=["hi"], voice="Serena"))[0].file != base
    assert scene_speech(_params(scene_lines=["hi"], audio_seed=8))[0].file != base
    assert scene_speech(_params(scene_lines=["hi"], frame_count=121))[0].file != base
    assert scene_speech(_params(scene_lines=["hi"], voice=speech.CUSTOM_VOICE,
                                voice_sample="C:/v/her.wav"))[0].file != base


def test_the_voice_is_a_preset_unless_the_custom_one_is_chosen():
    assert voice_request(_params()) == {"mode": "preset", "speaker": "Vivian"}
    assert voice_request(_params(voice=""))["speaker"] == speech.VOICE_PRESETS[0]
    # a recording named under a preset voice is not what speaks
    assert voice_request(_params(voice="Serena", voice_sample="C:/v/her.wav"))["mode"] == "preset"
    assert voice_request(_params(voice=speech.CUSTOM_VOICE, voice_sample=" C:/v/her.wav ",
                                 voice_sample_text=" Hello. ")) == {
        "mode": "clone", "sample": "C:/v/her.wav", "sample_text": "Hello."}


def test_a_custom_voice_without_a_recording_is_a_plain_error(tmp_path):
    run, _ = _speaking_run(tmp_path)
    with pytest.raises(SpeechError, match="Voice Sample names no file"):
        speech.ensure_speech_files(_params(scene_lines=["hi"], voice=speech.CUSTOM_VOICE),
                                   input_dir=tmp_path, python=Path("py"), run=run)
    with pytest.raises(SpeechError, match="not a file"):
        speech.ensure_speech_files(
            _params(scene_lines=["hi"], voice=speech.CUSTOM_VOICE, voice_sample=str(tmp_path / "gone.wav")),
            input_dir=tmp_path, python=Path("py"), run=run)


# ---- making the files --------------------------------------------------------


def _speaking_run(input_dir):
    """A stand-in for the worker: writes the files the job names, and records
    what it was run with."""
    calls = []

    def run(cmd, **kwargs):
        import json
        calls.append((cmd, kwargs))
        job = json.loads(Path(cmd[2]).read_text(encoding="utf-8"))
        for item in job["items"]:
            Path(item["out"]).parent.mkdir(parents=True, exist_ok=True)
            Path(item["out"]).write_bytes(b"RIFF")
        calls[-1] = (cmd, kwargs, job)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run, calls


def test_nothing_runs_when_no_line_is_missing(tmp_path):
    run, calls = _speaking_run(tmp_path)
    assert speech.ensure_speech_files(_params(), input_dir=tmp_path, python=Path("py"), run=run) == []
    params = _params(scene_lines=["hi"])
    file = tmp_path / scene_speech(params)[0].file
    file.parent.mkdir(parents=True)
    file.write_bytes(b"RIFF")
    assert speech.ensure_speech_files(params, input_dir=tmp_path, python=Path("py"), run=run) == []
    assert calls == []


def test_the_missing_lines_are_spoken_by_the_worker_under_the_speech_python(tmp_path):
    run, calls = _speaking_run(tmp_path)
    params = _params(frame_count=241, scene_frames=[161, 81], scene_lines=["Come in.", "Sit."],
                     audio_seed=3)
    made = speech.ensure_speech_files(params, input_dir=tmp_path, python=Path("C:/env/python.exe"),
                                      worker=Path("worker.py"), run=run)
    assert made == [tmp_path / scene.file for scene in scene_speech(params)]
    assert all(path.exists() for path in made)
    (cmd, kwargs, job), = calls
    assert cmd[:2] == [str(Path("C:/env/python.exe")), str(Path("worker.py"))]
    assert kwargs["capture_output"] and kwargs["text"]
    assert job["voice"] == {"mode": "preset", "speaker": "Vivian"}
    assert job["seed"] == 3
    assert [(item["text"], item["seconds"]) for item in job["items"]] == [
        ("Come in.", pytest.approx(161 / 16)), ("Sit.", pytest.approx(81 / 16))]
    assert [item["out"] for item in job["items"]] == [str(path) for path in made]
    assert not list((tmp_path / SPEECH_DIR).glob("job_*.json"))  # the job file is cleared


def test_only_the_lines_without_a_file_are_spoken(tmp_path):
    run, calls = _speaking_run(tmp_path)
    params = _params(frame_count=241, scene_frames=[161, 81], scene_lines=["a", "b"])
    first = tmp_path / scene_speech(params)[0].file
    first.parent.mkdir(parents=True)
    first.write_bytes(b"RIFF")
    made = speech.ensure_speech_files(params, input_dir=tmp_path, python=Path("py"), run=run)
    assert made == [tmp_path / scene_speech(params)[1].file]
    assert [item["text"] for item in calls[0][2]["items"]] == ["b"]


def test_a_missing_speech_python_is_a_plain_error(tmp_path):
    run, _ = _speaking_run(tmp_path)
    with pytest.raises(SpeechError, match="speech_python"):
        speech.ensure_speech_files(_params(scene_lines=["hi"]), input_dir=tmp_path, python=None, run=run)


def test_a_worker_that_fails_or_writes_nothing_is_an_error_with_its_words(tmp_path):
    def failing(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="no module named qwen_tts")

    with pytest.raises(SpeechError, match="qwen_tts"):
        speech.ensure_speech_files(_params(scene_lines=["hi"]), input_dir=tmp_path,
                                   python=Path("py"), run=failing)

    def silent(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(SpeechError, match="wrote nothing"):
        speech.ensure_speech_files(_params(scene_lines=["hi"]), input_dir=tmp_path,
                                   python=Path("py"), run=silent)


# ---- the worker's own arithmetic ------------------------------------------------


def test_a_line_is_padded_with_silence_or_cut_to_its_scenes_seconds():
    wave = np.ones(24000, dtype=np.float32)
    padded = speech_worker.fit_to_seconds(wave, 24000, 2.5)
    assert len(padded) == 60000 and padded[:24000].tolist() == wave.tolist()
    assert not padded[24000:].any()
    cut = speech_worker.fit_to_seconds(wave, 24000, 0.5)
    assert len(cut) == 12000 and cut.dtype == np.float32
