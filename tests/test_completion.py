from __future__ import annotations

from functools import partial
from pathlib import Path

from app_support.funscript import read_actions
from PIL import Image

import origenerator.workflows.wan22_animate as animate
from origenerator import config, gallery
from origenerator.completion import extract_completion
from origenerator.config import MOTION_DEFAULT_HZ
from origenerator.funscript import (
    funscript_of,
    synthesize_actions,
    synthesize_funscript,
    video_duration_seconds,
    write_funscript,
)
from origenerator.output_places import OutputPlaces
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.frame_rate import NATIVE_FPS
from tests.media_files import write_mp4

SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]
SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}
I2V = WORKFLOW_REGISTRY["wan22_i2v"]
FLF2V = WORKFLOW_REGISTRY["wan22_flf2v_loop"]


def _video_history(node_id, key, filename, subfolder="video"):
    return {"outputs": {node_id: {key: [{"filename": filename, "subfolder": subfolder}]}}}


def _history_with_duration(seconds):
    ms = int(seconds * 1000)
    return {
        "outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}},
        "status": {"messages": [
            ["execution_start", {"timestamp": 1_000}],
            ["execution_success", {"timestamp": 1_000 + ms}],
        ]},
    }


def test_extracts_output_files(tmp_path):
    files, thumb, duration = extract_completion(
        SDXL, SDXL_HISTORY, OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs", "n1"
    )
    assert files == [{"filename": "a.png", "subfolder": ""}]
    assert thumb is None  # a.png isn't on disk, so no thumbnail
    assert duration is None  # no timing in this history


def test_renders_thumbnail_when_output_is_on_disk(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out / "a.png")

    _files, thumb, _dur = extract_completion(
        SDXL, SDXL_HISTORY, OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "n1"
    )

    assert thumb is not None
    assert Path(thumb).exists()


def test_parses_execution_duration(tmp_path):
    _files, _thumb, duration = extract_completion(
        SDXL, _history_with_duration(12.5), OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs", "n1"
    )
    assert duration == 12.5


def test_no_output_yields_no_files_or_thumbnail(tmp_path):
    files, thumb, _dur = extract_completion(
        SDXL, {"outputs": {}}, OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs", "n1"
    )
    assert files == []
    assert thumb is None


def test_completing_a_video_synthesizes_a_funscript(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "video").mkdir(parents=True)
    (out / "video" / "wan22_i2v_00001_.mp4").write_bytes(b"v")
    calls = []
    monkeypatch.setattr(
        "origenerator.completion.synthesize_funscript",
        lambda video_path, *, hz, places: calls.append((Path(video_path), hz, places)),
    )
    extract_completion(
        I2V, _video_history("19", "images", "wan22_i2v_00001_.mp4"),
        OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "n1",
    )
    assert calls == [(out / "video" / "wan22_i2v_00001_.mp4", MOTION_DEFAULT_HZ,
                      OutputPlaces.in_one_folder(out))]


def test_a_video_given_a_deleted_videos_name_is_scripted_for_its_own_length(tmp_path):
    out = tmp_path / "out"
    video = out / "video" / "wan22_i2v_00001_.mp4"
    history = _video_history("19", "images", video.name)
    write_mp4(video, seconds=15.0)
    extract_completion(I2V, history, OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "deleted")
    video.unlink()

    write_mp4(video, seconds=5.0)
    extract_completion(I2V, history, OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "namesake")

    assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(out))) == synthesize_actions(
        video_duration_seconds(video), hz=MOTION_DEFAULT_HZ)


def test_a_video_made_for_genau_is_scripted_as_exactly_one_cycle(tmp_path, monkeypatch):
    out = tmp_path / "out"
    video = out / "video" / "flf2v_loop_00001.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    cycle_seconds = gallery.CYCLE_FRAMES / NATIVE_FPS
    monkeypatch.setattr(
        "origenerator.completion.synthesize_funscript",
        partial(synthesize_funscript, duration_provider=lambda _video: cycle_seconds),
    )

    extract_completion(
        FLF2V, _video_history("16", "gifs", video.name),
        OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "n1",
    )

    actions = read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(out)))
    assert [a["pos"] for a in actions] == [0, 100, 0]
    assert actions[-1]["at"] == round(cycle_seconds * 1000)


def test_a_video_performed_from_a_library_video_takes_that_videos_script(tmp_path, monkeypatch):
    performs = WORKFLOW_REGISTRY["wan22_animate"]
    videos, scripts = tmp_path / "videos" / "videos", tmp_path / "videos" / "scripts" / "scripts"
    monkeypatch.setattr(config, "LIBRARY_VIDEOS_DIR", videos)
    monkeypatch.setattr(config, "LIBRARY_SCRIPTS_DIR", scripts)
    monkeypatch.setattr(animate, "video_duration_seconds", lambda path: 60.0)
    driving = videos / "scene one.mp4"
    driving.parent.mkdir(parents=True)
    driving.write_bytes(b"v")
    write_funscript(scripts / "scene one.funscript", synthesize_actions(60.0, hz=0.5))
    out = tmp_path / "out"
    video = out / "video" / "wan22_animate_00001_.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    metronome = []
    monkeypatch.setattr("origenerator.completion.synthesize_funscript",
                        lambda *a, **k: metronome.append((a, k)))
    params = dict(performs.default_params(), video=str(driving), video_start=2.0, frame_count=81)

    extract_completion(performs, _video_history("24", "gifs", video.name),
                       OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "n1", params=params)

    assert read_actions(funscript_of(video, places=OutputPlaces.in_one_folder(out))) == (
        performs.authored_actions(params))
    assert metronome == []


def test_completing_an_image_writes_no_funscript(tmp_path, monkeypatch):
    Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / "a.png")
    calls = []
    monkeypatch.setattr(
        "origenerator.completion.synthesize_funscript",
        lambda *a, **k: calls.append((a, k)),
    )
    extract_completion(SDXL, SDXL_HISTORY, OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs", "n1")
    assert calls == []  # a still image has nothing to drive a device with


def test_a_script_that_cannot_be_written_never_strands_a_finished_video(tmp_path, monkeypatch):
    out = tmp_path / "out"
    video = write_mp4(out / "video" / "wan22_i2v_00001_.mp4", seconds=1.0)

    def refuse(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("origenerator.completion.synthesize_funscript", refuse)
    files, _thumb, _duration = extract_completion(
        I2V, _video_history("19", "images", video.name), OutputPlaces.in_one_folder(out), tmp_path / "thumbs", "n1")

    assert files == [{"filename": video.name, "subfolder": "video"}]


def test_a_finished_run_is_filed_in_the_library_before_its_thumbnail_is_drawn(tmp_path):
    library = tmp_path / "library"
    places = OutputPlaces(comfyui=tmp_path / "comfyui saves", images=library / "images",
                          videos=library / "videos", scripts=library / "scripts",
                          audio=library / "sounds")
    waiting = places.run("n1") / "image"
    waiting.mkdir(parents=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(waiting / "sdxl_t2i_00001_.png")
    history = {"outputs": {"7": {"images": [
        {"filename": "sdxl_t2i_00001_.png", "subfolder": "origenerator/n1/image", "type": "output"}]}}}

    files, thumb, _duration = extract_completion(SDXL, history, places, tmp_path / "thumbs", "n1")

    assert files == [{"filename": "sdxl_t2i_00001_.png", "subfolder": "image", "type": "output"}]
    assert (places.images / "sdxl_t2i_00001_.png").is_file()
    assert thumb is not None
    assert Path(thumb).is_file()
