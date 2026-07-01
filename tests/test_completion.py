from pathlib import Path

from PIL import Image

from origenerator.completion import extract_completion
from origenerator.workflows import WORKFLOW_REGISTRY

SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]
SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


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
