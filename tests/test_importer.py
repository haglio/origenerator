import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from origenerator.db import Database
from origenerator.importer import import_comfyui_output


def _make_png_with_metadata(path, prompt_data):
    """Create a PNG with ComfyUI-style metadata embedded."""
    img = Image.new("RGB", (64, 64), (128, 0, 0))
    pnginfo = PngInfo()
    pnginfo.add_text("prompt", json.dumps(prompt_data))
    img.save(path, pnginfo=pnginfo)


def test_import_png_extracts_metadata(tmp_path):
    output_dir = tmp_path / "output" / "image"
    output_dir.mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"

    prompt_data = {
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a beautiful sunset", "clip": ["1", 1]},
            "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "ugly", "clip": ["1", 1]},
            "_meta": {"title": "CLIP Text Encode (Negative Prompt)"},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {"seed": 12345, "steps": 50, "cfg": 7.5},
        },
    }
    _make_png_with_metadata(output_dir / "test_00001_.png", prompt_data)

    db = Database(tmp_path / "test.db")
    count = import_comfyui_output(output_dir.parent, db, thumb_dir)
    assert count == 1

    rows = db.list_generations()
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "imported"
    assert row["status"] == "completed"
    assert row["positive_prompt"] == "a beautiful sunset"
    assert row["negative_prompt"] == "ugly"
    assert row["seed"] == 12345


def test_import_video_infers_workflow_from_filename_prefix(tmp_path):
    output_dir = tmp_path / "output" / "video"
    output_dir.mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"

    # ComfyUI names outputs "<prefix>_NNNNN_.mp4"; the prefix identifies the workflow.
    (output_dir / "wan22_i2v_842719365028413_00001_.mp4").write_bytes(b"")
    (output_dir / "flf2v_loop_00001.mp4").write_bytes(b"")
    (output_dir / "mystery_clip_00001.mp4").write_bytes(b"")

    db = Database(tmp_path / "test.db")
    import_comfyui_output(output_dir.parent, db, thumb_dir)

    name_by_file = {}
    for row in db.list_generations():
        files = json.loads(row["output_files"])
        name_by_file[files[0]["filename"]] = row["workflow_name"]

    assert name_by_file["wan22_i2v_842719365028413_00001_.mp4"] == "wan22_i2v"
    assert name_by_file["flf2v_loop_00001.mp4"] == "wan22_flf2v_loop"
    assert name_by_file["mystery_clip_00001.mp4"] == "unknown"


def test_import_skips_already_imported(tmp_path):
    output_dir = tmp_path / "output" / "image"
    output_dir.mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"

    _make_png_with_metadata(output_dir / "test_00001_.png", {"2": {}})

    db = Database(tmp_path / "test.db")
    assert import_comfyui_output(output_dir.parent, db, thumb_dir) == 1
    assert import_comfyui_output(output_dir.parent, db, thumb_dir) == 0
