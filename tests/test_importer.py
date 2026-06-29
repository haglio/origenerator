import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from origenerator.db import Database
from origenerator.importer import (
    backfill_unknown_workflows,
    import_comfyui_output,
    merge_video_sidecar_rows,
)


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


def test_backfill_relabels_unknown_imports_by_filename(tmp_path):
    db = Database(tmp_path / "test.db")

    def add_unknown(prompt_id, filename):
        db.insert_generation(
            prompt_id=prompt_id, workflow_name="unknown",
            workflow_version="imported", params_json="{}",
            workflow_json="{}", source="imported",
        )
        db.update_generation(prompt_id, output_files=json.dumps(
            [{"filename": filename, "subfolder": "video", "type": "output"}]
        ))

    add_unknown("bf-i2v", "wan22_i2v_842719365028413_00001_.mp4")
    add_unknown("bf-mystery", "mystery_00001.mp4")
    # An already-identified row must be left untouched.
    db.insert_generation(
        prompt_id="bf-known", workflow_name="wan22_flf2v_loop",
        workflow_version="v004", params_json="{}", workflow_json="{}",
    )

    updated = backfill_unknown_workflows(db)

    assert updated == 1
    assert db.get_generation("bf-i2v")["workflow_name"] == "wan22_i2v"
    assert db.get_generation("bf-mystery")["workflow_name"] == "unknown"
    assert db.get_generation("bf-known")["workflow_name"] == "wan22_flf2v_loop"


def test_extract_metadata_from_video_recovers_prompts_image_dims(tmp_path, monkeypatch):
    import origenerator.importer as imp
    # No _meta titles: prompts must be found structurally via the Wan node's links.
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "start.png"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a serene lake"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
        "4": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 555, "add_noise": "enable"}},
        "5": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["2", 0], "negative": ["3", 0], "start_image": ["1", 0],
            "width": 768, "height": 512, "length": 81}},
    }
    monkeypatch.setattr(imp, "_video_prompt_graph", lambda p: graph)
    meta = imp._extract_metadata(tmp_path / "wan22_i2v_555_00001_.mp4", ".mp4")
    assert meta["positive_prompt"] == "a serene lake"
    assert meta["negative_prompt"] == "blurry"
    assert meta["seed"] == 555
    assert meta["params"]["input_image"] == "start.png"
    assert meta["params"]["width"] == 768
    assert meta["params"]["frame_count"] == 81
    assert meta["workflow_name"] == "wan22_i2v"


def test_video_prompt_graph_handles_double_encoded(tmp_path, monkeypatch):
    import subprocess as sp
    import origenerator.importer as imp
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}}}
    double = json.dumps(json.dumps(graph))  # VHS_VideoCombine double-encodes
    out = json.dumps({"format": {"tags": {"prompt": double}}})
    monkeypatch.setattr(imp.shutil, "which", lambda n: "ffprobe")
    monkeypatch.setattr(imp.subprocess, "run",
                        lambda *a, **k: sp.CompletedProcess(a, 0, stdout=out, stderr=""))
    g = imp._video_prompt_graph(tmp_path / "v.mp4")
    assert g["1"]["class_type"] == "LoadImage"


def test_video_prompt_graph_empty_without_ffprobe(tmp_path, monkeypatch):
    import origenerator.importer as imp
    monkeypatch.setattr(imp.shutil, "which", lambda n: None)
    assert imp._video_prompt_graph(tmp_path / "v.mp4") == {}


def test_import_skips_already_imported(tmp_path):
    output_dir = tmp_path / "output" / "image"
    output_dir.mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"

    _make_png_with_metadata(output_dir / "test_00001_.png", {"2": {}})

    db = Database(tmp_path / "test.db")
    assert import_comfyui_output(output_dir.parent, db, thumb_dir) == 1
    assert import_comfyui_output(output_dir.parent, db, thumb_dir) == 0


def test_import_consolidates_video_with_metadata_png_sidecar(tmp_path):
    output_dir = tmp_path / "output" / "video"
    output_dir.mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"

    # VHS_VideoCombine writes a metadata PNG beside the MP4; the PNG carries the
    # prompt/seed, the MP4 is the playable output. The Wan conditioning node
    # links to the prompts, the way the embedded graph really does.
    prompt_data = {
        "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "a dancing cat"}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
        "12": {"class_type": "WanFirstLastFrameToVideo",
               "inputs": {"positive": ["9", 0], "negative": ["10", 0]}},
        "13": {"class_type": "KSamplerAdvanced",
               "inputs": {"noise_seed": 777, "add_noise": "enable"}},
    }
    _make_png_with_metadata(output_dir / "flf2v_loop_00001.png", prompt_data)
    (output_dir / "flf2v_loop_00001.mp4").write_bytes(b"")

    db = Database(tmp_path / "test.db")
    count = import_comfyui_output(output_dir.parent, db, thumb_dir)

    assert count == 1  # one entry, not one-per-file
    rows = db.list_generations()
    assert len(rows) == 1
    row = rows[0]
    files = json.loads(row["output_files"])
    assert files[0]["filename"] == "flf2v_loop_00001.mp4"   # plays the video
    assert row["positive_prompt"] == "a dancing cat"        # keeps the PNG metadata
    assert row["seed"] == 777
    assert row["workflow_name"] == "wan22_flf2v_loop"


def test_import_standalone_video_without_sidecar_still_imports(tmp_path):
    output_dir = tmp_path / "output" / "video"
    output_dir.mkdir(parents=True)
    (output_dir / "wan22_i2v_00001_.mp4").write_bytes(b"")

    db = Database(tmp_path / "test.db")
    assert import_comfyui_output(output_dir.parent, db, tmp_path / "thumbs") == 1
    files = json.loads(db.list_generations()[0]["output_files"])
    assert files[0]["filename"] == "wan22_i2v_00001_.mp4"


def _completed(db, prompt_id, filename, subfolder, **fields):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name=fields.get("workflow_name", "wan22_flf2v_loop"),
        workflow_version="imported", positive_prompt=fields.get("positive_prompt"),
        seed=fields.get("seed"), params_json=fields.get("params_json", "{}"),
        workflow_json="{}", source="imported",
    )
    db.update_generation(
        prompt_id, status="completed",
        output_files=json.dumps([{"filename": filename, "subfolder": subfolder}]),
        thumbnail_path=fields.get("thumbnail_path"),
    )


def test_merge_repoints_image_sidecar_to_video_and_drops_video_row(tmp_path):
    db = Database(tmp_path / "test.db")
    _completed(db, "img", "flf2v_loop_00001.png", "video",
               positive_prompt="a dancing cat", seed=777,
               params_json=json.dumps({"steps": 4, "seed": 777}),
               thumbnail_path="thumbs/flf2v_loop_00001.jpg")
    _completed(db, "vid", "flf2v_loop_00001.mp4", "video")

    assert merge_video_sidecar_rows(db) == 1
    assert db.get_generation("vid") is None              # redundant video row gone
    survivor = db.get_generation("img")
    files = json.loads(survivor["output_files"])
    assert files[0]["filename"] == "flf2v_loop_00001.mp4"   # now plays the video
    assert survivor["positive_prompt"] == "a dancing cat"   # metadata preserved
    assert survivor["thumbnail_path"] == "thumbs/flf2v_loop_00001.jpg"


def test_merge_leaves_standalone_rows_untouched(tmp_path):
    db = Database(tmp_path / "test.db")
    _completed(db, "solo-img", "sdxl_t2i_1_.png", "image", workflow_name="sdxl_t2i")
    _completed(db, "solo-vid", "wan22_i2v_1_.mp4", "video", workflow_name="wan22_i2v")

    assert merge_video_sidecar_rows(db) == 0
    assert db.get_generation("solo-img") is not None
    assert db.get_generation("solo-vid") is not None
