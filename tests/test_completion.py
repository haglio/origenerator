from pathlib import Path

from PIL import Image

from origenerator.completion import extract_completion
from origenerator.config import STROKE_DEFAULT_HZ
from origenerator.workflows import WORKFLOW_REGISTRY

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
        SDXL, SDXL_HISTORY, tmp_path, tmp_path / "thumbs", "n1"
    )
    assert files == [{"filename": "a.png", "subfolder": ""}]
    assert thumb is None  # a.png isn't on disk, so no thumbnail
    assert duration is None  # no timing in this history


def test_renders_thumbnail_when_output_is_on_disk(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out / "a.png")

    _files, thumb, _dur = extract_completion(
        SDXL, SDXL_HISTORY, out, tmp_path / "thumbs", "n1"
    )

    assert thumb is not None and Path(thumb).exists()


def test_parses_execution_duration(tmp_path):
    _files, _thumb, duration = extract_completion(
        SDXL, _history_with_duration(12.5), tmp_path, tmp_path / "thumbs", "n1"
    )
    assert duration == 12.5


def test_no_output_yields_no_files_or_thumbnail(tmp_path):
    files, thumb, _dur = extract_completion(
        SDXL, {"outputs": {}}, tmp_path, tmp_path / "thumbs", "n1"
    )
    assert files == [] and thumb is None


def test_completing_a_video_synthesizes_a_funscript(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "video").mkdir(parents=True)
    (out / "video" / "wan22_i2v_00001_.mp4").write_bytes(b"v")
    calls = []
    monkeypatch.setattr(
        "origenerator.completion.ensure_funscript",
        lambda video_path, *, loop, hz: calls.append((Path(video_path), loop, hz)),
    )
    extract_completion(
        I2V, _video_history("19", "images", "wan22_i2v_00001_.mp4"),
        out, tmp_path / "thumbs", "n1",
    )
    # The synthesized script rides next to the real output file, one-shot (not looped),
    # at the configured cadence.
    assert calls == [(out / "video" / "wan22_i2v_00001_.mp4", False, STROKE_DEFAULT_HZ)]


def test_completing_a_loop_video_asks_for_a_looping_funscript(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "video").mkdir(parents=True)
    (out / "video" / "flf2v_loop_00001.mp4").write_bytes(b"v")
    calls = []
    monkeypatch.setattr(
        "origenerator.completion.ensure_funscript",
        lambda video_path, *, loop, hz: calls.append(loop),
    )
    extract_completion(
        FLF2V, _video_history("16", "gifs", "flf2v_loop_00001.mp4"),
        out, tmp_path / "thumbs", "n1",
    )
    assert calls == [True]  # the loop workflow → a seamlessly-tiling script


def test_completing_an_image_writes_no_funscript(tmp_path, monkeypatch):
    Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / "a.png")
    calls = []
    monkeypatch.setattr(
        "origenerator.completion.ensure_funscript",
        lambda *a, **k: calls.append((a, k)),
    )
    extract_completion(SDXL, SDXL_HISTORY, tmp_path, tmp_path / "thumbs", "n1")
    assert calls == []  # a still image has nothing to drive a device with
