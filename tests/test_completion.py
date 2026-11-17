from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from origenerator import completion
from origenerator.funscript import funscript_of
from origenerator.output_places import OutputFolders, OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path
from origenerator.workflows import WORKFLOW_REGISTRY
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
    files, thumb, duration = completion.extract_completion(
        SDXL, SDXL_HISTORY, OutputFolders(OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs"), "n1"
    )
    assert files == [{"filename": "a.png", "subfolder": ""}]
    assert thumb is None
    assert duration is None


def test_renders_thumbnail_when_output_is_on_disk(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out / "a.png")

    _files, thumb, _dur = completion.extract_completion(
        SDXL, SDXL_HISTORY, OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1"
    )

    assert thumb is not None
    assert Path(thumb).exists()


def test_a_time_that_cannot_be_read_never_strands_a_finished_run(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.png").write_bytes(b"not an image either")

    def unreadable(history):
        raise ValueError("no times in this history")

    monkeypatch.setattr(completion, "execution_duration_seconds", unreadable)

    try:
        files, _thumb, duration = completion.extract_completion(
            SDXL, _history_with_duration(3.0),
            OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1")
    except ValueError:
        pytest.fail("the thumbnail and the duration are best-effort: a failure in either yields "
                    "None rather than stranding an otherwise finished run")

    assert files == [{"filename": "a.png", "subfolder": ""}]
    assert duration is None


def test_a_thumbnail_that_cannot_be_drawn_never_strands_a_finished_run(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.png").write_bytes(b"this is not a picture")

    files, thumb, duration = completion.extract_completion(
        SDXL, _history_with_duration(3.0), OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1"
    )

    assert files == [{"filename": "a.png", "subfolder": ""}]
    assert thumb is None
    assert duration == 3.0


def test_a_duration_that_cannot_be_read_never_strands_a_finished_run(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.png").write_bytes(b"this is not an image")

    def unreadable(history):
        raise ValueError("no timing in this history")

    monkeypatch.setattr(completion, "execution_duration_seconds", unreadable)

    files, _thumb, duration = completion.extract_completion(
        SDXL, _history_with_duration(3.0), OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1"
    )

    assert files == [{"filename": "a.png", "subfolder": ""}], (
        "how long a run took is nice to know; failing to read it must never strand a real completion")
    assert duration is None


def test_parses_execution_duration(tmp_path):
    _files, _thumb, duration = completion.extract_completion(
        SDXL, _history_with_duration(12.5), OutputFolders(OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs"), "n1"
    )
    assert duration == 12.5


def test_no_output_yields_no_files_or_thumbnail(tmp_path):
    files, thumb, _dur = completion.extract_completion(
        SDXL, {"outputs": {}}, OutputFolders(OutputPlaces.in_one_folder(tmp_path), tmp_path / "thumbs"), "n1"
    )
    assert files == []
    assert thumb is None


def test_a_completed_video_has_its_thumbnail_ready_to_animate(tmp_path):
    out = tmp_path / "out"
    write_mp4(out / "video" / "wan22_i2v_00001_.mp4")

    completion.extract_completion(I2V, _video_history("19", "images", "wan22_i2v_00001_.mp4"),
                       OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1")

    assert animated_thumbnail_path(tmp_path / "thumbs", "n1").exists()


def test_a_completed_image_has_no_thumbnail_to_animate(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (8, 8)).save(out / "a.png")

    completion.extract_completion(SDXL, SDXL_HISTORY, OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1")

    assert not animated_thumbnail_path(tmp_path / "thumbs", "n1").exists()


def test_a_finished_video_is_left_for_goblinscript_with_no_funscript_of_origenerators(tmp_path):
    out = tmp_path / "out"
    video = write_mp4(out / "video" / "wan22_i2v_00001_.mp4", seconds=1.0)

    files, _thumb, _duration = completion.extract_completion(
        I2V, _video_history("19", "images", video.name), OutputFolders(OutputPlaces.in_one_folder(out), tmp_path / "thumbs"), "n1")

    assert files == [{"filename": video.name, "subfolder": "video"}]
    assert funscript_of(video, places=OutputPlaces.in_one_folder(out)) is None
    assert not list(out.rglob("*.funscript"))


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

    files, thumb, _duration = completion.extract_completion(SDXL, history, OutputFolders(places, tmp_path / "thumbs"), "n1")

    assert files == [{"filename": "sdxl_t2i_00001_.png", "subfolder": "image", "type": "output"}]
    assert (places.images / "sdxl_t2i_00001_.png").is_file()
    assert thumb is not None
    assert Path(thumb).is_file()


ENHANCE = WORKFLOW_REGISTRY["image_enhance"]
BEFORE_THE_FIX, FIXED = (10, 10, 10), (200, 0, 0)


def _an_enhance_run_with_one_fix(tmp_path, *, graph=True):
    library = tmp_path / "library"
    places = OutputPlaces(comfyui=tmp_path / "comfyui saves", images=library / "images",
                          videos=library / "videos", scripts=library / "scripts",
                          audio=library / "sounds")
    saved, before = places.run("n1") / "image", places.run("n1") / "before fixes"
    saved.mkdir(parents=True)
    before.mkdir()
    Image.new("RGB", (100, 100), BEFORE_THE_FIX).save(before / "fix0_00001_.png")
    enhanced = Image.new("RGB", (100, 100), BEFORE_THE_FIX)
    enhanced.paste(FIXED, (10, 10, 40, 40))
    enhanced.save(saved / "image_enhance_00001_.png")
    history = {"outputs": {
        "12": {"images": [{"filename": "image_enhance_00001_.png",
                           "subfolder": "origenerator/n1/image", "type": "output"}]},
        "fix0_before": {"images": [{"filename": "fix0_00001_.png",
                                    "subfolder": "origenerator/n1/before fixes", "type": "output"}]},
        "fix0_points": {"text": ["[10, 10, 40, 40]", "[0, 0, 100, 100]"]}}}
    if graph:
        history["prompt"] = [1, "n1", {"fix0_detector": {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": "bbox/face_finder.pt"}}}, {}, []]
    return places, history


def test_a_finished_enhancement_keeps_what_each_fix_redrew_and_none_of_the_whole_images(tmp_path):
    places, history = _an_enhance_run_with_one_fix(tmp_path)

    files, _thumb, _duration = completion.extract_completion(
        ENHANCE, history, OutputFolders(places, tmp_path / "thumbnails"), "n1")

    assert files[0]["fixes"] == [{"part": "faces", "box": [10, 10, 40, 40], "over": []}]
    kept = tmp_path / "kept from fixes" / files[0]["fixes_kept"]
    with Image.open(kept / "0_before.png") as under_the_fix:
        assert under_the_fix.size == (30, 30)
        assert under_the_fix.getpixel((0, 0)) == BEFORE_THE_FIX
    assert not places.run("n1").exists()


def test_an_enhancement_whose_fixes_cannot_be_named_keeps_nothing_and_leaves_no_whole_image(tmp_path):
    places, history = _an_enhance_run_with_one_fix(tmp_path, graph=False)

    files, _thumb, _duration = completion.extract_completion(
        ENHANCE, history, OutputFolders(places, tmp_path / "thumbnails"), "n1")

    assert "fixes" not in files[0]
    assert not (tmp_path / "kept from fixes").exists()
    assert not places.run("n1").exists()
