import json
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from origenerator.db import Database
from origenerator.importer import (
    backfill_input_image,
    backfill_model_and_lora_params,
    backfill_shared_thumbnails,
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


def test_backfill_fills_model_and_lora_params_from_stored_graph(tmp_path):
    db = Database(tmp_path / "test.db")
    # An early import: the graph is on the row, but its UNET/LoRA were never
    # pulled into params, so it can't nest by model or LoRA yet.
    graph = {
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_high.safetensors"}},
        "5": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_low.safetensors"}},
        "6": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["4", 0], "lora_name": "styleB_high.safetensors"}},
        "7": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["5", 0], "lora_name": "styleB_low.safetensors"}},
        "15": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["6", 0], "add_noise": "enable"}},
        "16": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["7", 0], "add_noise": "disable"}},
    }
    db.insert_generation(
        prompt_id="old", workflow_name="wan22_i2v", workflow_version="imported",
        params_json=json.dumps({"positive_prompt": "a fox", "seed": 1}),
        workflow_json=json.dumps(graph), source="imported",
    )
    # A row that already carries its model + LoRA is left alone.
    db.insert_generation(
        prompt_id="fresh", workflow_name="wan22_i2v", workflow_version="v001",
        params_json=json.dumps({
            "unet_high": "u_h.safetensors", "unet_low": "u_l.safetensors",
            "lora_high": "l_h.safetensors", "lora_low": "l_l.safetensors",
        }),
        workflow_json=json.dumps(graph),
    )

    updated = backfill_model_and_lora_params(db)

    assert updated == 1
    old = json.loads(db.get_generation("old")["params_json"])
    assert old["unet_high"] == "wan_high.safetensors"
    assert old["lora_high"] == "styleB_high.safetensors"
    assert old["lora_low"] == "styleB_low.safetensors"
    assert old["positive_prompt"] == "a fox"  # existing params kept
    # The already-complete row's LoRA is not overwritten by the graph's.
    assert json.loads(db.get_generation("fresh")["params_json"])["lora_high"] == "l_h.safetensors"
    # Idempotent: a second pass finds nothing left to fill.
    assert backfill_model_and_lora_params(db) == 0


def test_backfill_fills_input_image_from_stored_graph(tmp_path):
    db = Database(tmp_path / "test.db")
    # An early video import: the graph is on the row (LoadImage names the source
    # frame), but input_image was never pulled into params, so the video can't
    # link back to the gallery image it was animated from.
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "sdxl_t2i_00022_.png"}},
        "5": {"class_type": "WanFirstLastFrameToVideo", "inputs": {"start_image": ["1", 0]}},
    }
    db.insert_generation(
        prompt_id="old", workflow_name="wan22_flf2v_loop", workflow_version="imported",
        params_json=json.dumps({"positive_prompt": "a fox", "seed": 1}),
        workflow_json=json.dumps(graph), source="imported",
    )
    # A row that already names its input image is left alone — a re-roll's fresh
    # start-frame reference must not be clobbered by the graph's original.
    db.insert_generation(
        prompt_id="fresh", workflow_name="wan22_flf2v_loop", workflow_version="v005",
        params_json=json.dumps({"input_image": "video/x_00001.mp4 [output]"}),
        workflow_json=json.dumps(graph),
    )
    # A row whose graph loads no image (a text-to-image) has no source to recover.
    db.insert_generation(
        prompt_id="t2i", workflow_name="sdxl_t2i", workflow_version="imported",
        params_json=json.dumps({"seed": 9}),
        workflow_json=json.dumps({"5": {"class_type": "KSampler", "inputs": {}}}),
        source="imported",
    )

    updated = backfill_input_image(db)

    assert updated == 1
    old = json.loads(db.get_generation("old")["params_json"])
    assert old["input_image"] == "sdxl_t2i_00022_.png"
    assert old["positive_prompt"] == "a fox"  # existing params kept
    # The re-rolled row's fresh input reference is preserved.
    assert json.loads(db.get_generation("fresh")["params_json"])["input_image"] == "video/x_00001.mp4 [output]"
    assert "input_image" not in json.loads(db.get_generation("t2i")["params_json"])
    # Idempotent: a second pass finds nothing left to fill.
    assert backfill_input_image(db) == 0


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


def test_extract_metadata_reads_high_low_unet_and_lora_from_graph(tmp_path, monkeypatch):
    import origenerator.importer as imp
    # An i2v variant differs from its siblings only by LoRA. The LoRA (and base
    # model) live in the two samplers' model chains; extracting them is what lets
    # the gallery nest the import under its model -> LoRA folders.
    graph = {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a fox"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_high.safetensors"}},
        "5": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_low.safetensors"}},
        "6": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["4", 0], "lora_name": "styleB_high.safetensors"}},
        "7": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["5", 0], "lora_name": "styleB_low.safetensors"}},
        "8": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["6", 0]}},
        "9": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["7", 0]}},
        "14": {"class_type": "WanImageToVideo",
               "inputs": {"positive": ["2", 0], "negative": ["3", 0],
                          "width": 720, "height": 544, "length": 121}},
        "15": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["8", 0], "noise_seed": 7, "add_noise": "enable"}},
        "16": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["9", 0], "add_noise": "disable"}},
    }
    monkeypatch.setattr(imp, "_video_prompt_graph", lambda p: graph)
    meta = imp._extract_metadata(tmp_path / "wan22_i2v_00001_.mp4", ".mp4")

    assert meta["workflow_name"] == "wan22_i2v"
    assert meta["params"]["unet_high"] == "wan_high.safetensors"
    assert meta["params"]["unet_low"] == "wan_low.safetensors"
    assert meta["params"]["lora_high"] == "styleB_high.safetensors"
    assert meta["params"]["lora_low"] == "styleB_low.safetensors"


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


def test_video_prompt_graph_runs_ffprobe_without_a_console_window(tmp_path, monkeypatch):
    """Each ffprobe child must be spawned windowless: importing a batch of videos
    calls it once per file, and on Windows an unsuppressed child flashes a console
    window per call. Assert the console-suppressing creationflag is passed."""
    import subprocess as sp
    import origenerator.importer as imp

    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return sp.CompletedProcess(args, 0, stdout=json.dumps({"format": {}}), stderr="")

    monkeypatch.setattr(imp.shutil, "which", lambda n: "ffprobe")
    monkeypatch.setattr(imp.subprocess, "run", fake_run)

    imp._video_prompt_graph(tmp_path / "v.mp4")

    assert captured.get("creationflags") == getattr(sp, "CREATE_NO_WINDOW", 0)


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


def test_import_same_stem_image_and_video_get_distinct_thumbnails(tmp_path):
    """A still and a clip that share a filename stem must not share a thumbnail.

    ComfyUI's default ``SaveImage`` prefix yields ``ComfyUI_00001_.png`` while a
    video lands at ``video/ComfyUI_00001_.mp4``; both import as separate rows.
    Naming the thumbnail by the source stem collapsed them onto one file, so the
    image row's thumbnail showed the video's frame even though its preview was
    the still. Each row must own a distinct, existing thumbnail.
    """
    output_dir = tmp_path / "output"
    (output_dir / "video").mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"
    _make_png_with_metadata(output_dir / "ComfyUI_00001_.png", {"2": {}})
    (output_dir / "video" / "ComfyUI_00001_.mp4").write_bytes(b"")

    db = Database(tmp_path / "test.db")
    assert import_comfyui_output(output_dir, db, thumb_dir) == 2

    thumbs = [r["thumbnail_path"] for r in db.list_generations()]
    assert all(thumbs) and len(set(thumbs)) == 2          # two distinct thumbnails
    assert all(Path(t).exists() for t in thumbs)          # neither overwritten away


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


def test_backfill_resplits_thumbnail_shared_by_a_stem_collision(tmp_path):
    """Repair the old collision: two rows pointing at one stem-named thumbnail.

    Before the per-prompt naming fix, ``ComfyUI_00001_.png`` and
    ``video/ComfyUI_00001_.mp4`` both wrote ``ComfyUI_00001_.jpg`` — the later
    import winning — so the image row's thumbnail showed the clip's frame. The
    backfill re-renders each sharer from its own output under its prompt_id.
    """
    output_dir = tmp_path / "output"
    (output_dir / "video").mkdir(parents=True)
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    Image.new("RGB", (512, 768), (255, 0, 0)).save(output_dir / "ComfyUI_00001_.png")
    (output_dir / "video" / "ComfyUI_00001_.mp4").write_bytes(b"")
    shared = thumb_dir / "ComfyUI_00001_.jpg"  # the single file both rows share
    Image.new("RGB", (256, 144), (0, 255, 0)).save(shared)  # currently the clip's frame

    db = Database(tmp_path / "test.db")
    _completed(db, "img", "ComfyUI_00001_.png", "", thumbnail_path=str(shared))
    _completed(db, "vid", "ComfyUI_00001_.mp4", "video", thumbnail_path=str(shared))

    assert backfill_shared_thumbnails(db, output_dir, thumb_dir) == 2

    img_thumb = db.get_generation("img")["thumbnail_path"]
    vid_thumb = db.get_generation("vid")["thumbnail_path"]
    assert img_thumb != vid_thumb
    assert Path(img_thumb).name == "img.jpg"   # named by prompt_id now
    assert Path(img_thumb).exists() and Path(vid_thumb).exists()
    # The image row's thumbnail reflects its own portrait still, not the clip.
    assert Image.open(img_thumb).size[0] < Image.open(img_thumb).size[1]


def test_backfill_leaves_a_uniquely_owned_thumbnail_untouched(tmp_path):
    """A thumbnail no other row shares (and that exists) is left exactly as is."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(output_dir / "sdxl_t2i_1_.png")
    thumb = thumb_dir / "sdxl_t2i_1_.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(thumb)

    db = Database(tmp_path / "test.db")
    _completed(db, "solo", "sdxl_t2i_1_.png", "", thumbnail_path=str(thumb))

    assert backfill_shared_thumbnails(db, output_dir, thumb_dir) == 0
    assert db.get_generation("solo")["thumbnail_path"] == str(thumb)


def test_backfill_regenerates_a_missing_thumbnail(tmp_path):
    """A completed row whose thumbnail file has vanished gets a fresh one.

    This is the tail of the same bug: deleting one stem-twin trashed the shared
    thumbnail, leaving the survivor pointing at a file that no longer exists.
    """
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    Image.new("RGB", (64, 64), (9, 9, 9)).save(output_dir / "sdxl_t2i_5_.png")

    db = Database(tmp_path / "test.db")
    _completed(db, "gone", "sdxl_t2i_5_.png", "",
               thumbnail_path=str(thumb_dir / "sdxl_t2i_5_.jpg"))  # never on disk

    assert backfill_shared_thumbnails(db, output_dir, thumb_dir) == 1
    new = db.get_generation("gone")["thumbnail_path"]
    assert Path(new).name == "gone.jpg"
    assert Path(new).exists()


def test_extract_metadata_identifies_flux_t2i_upscaled_from_graph(tmp_path):
    import origenerator.importer as imp
    # Flux embeds no checkpoint and no Wan node: its UnetLoaderGGUF + DualCLIPLoader
    # + FluxGuidance signature is what names it, and the GGUF model is pulled out
    # so the gallery can split Flux runs by which model made them. The filename
    # matches no workflow prefix, proving the embedded graph alone suffices.
    graph = {
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "ultrarealFineTune_v4_fp16.gguf"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "clip_l.safetensors",
                         "clip_name2": "t5xxl_fp16.safetensors", "type": "flux"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "a portrait"},
              "_meta": {"title": "Positive Prompt"}},
        "5": {"class_type": "FluxGuidance",
              "inputs": {"conditioning": ["4", 0], "guidance": 4.5}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""},
              "_meta": {"title": "Negative (empty)"}},
        "8": {"class_type": "KSampler",
              "inputs": {"seed": 355448440510534, "steps": 20, "cfg": 1.0}},
        "12": {"class_type": "SaveImage",
               "inputs": {"filename_prefix": "image/flux_t2i_upscaled"}},
    }
    _make_png_with_metadata(tmp_path / "renamed_flux.png", graph)
    meta = imp._extract_metadata(tmp_path / "renamed_flux.png", ".png")

    assert meta["workflow_name"] == "flux_t2i_upscaled"
    assert meta["positive_prompt"] == "a portrait"
    assert meta["seed"] == 355448440510534
    assert meta["params"]["unet"] == "ultrarealFineTune_v4_fp16.gguf"


def test_backfill_relabels_unknown_flux_import_by_filename(tmp_path):
    # The Flux imports that predate this workflow landed as "unknown"; once it's
    # registered, the flux_t2i_upscaled_* filename prefix identifies them.
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="flux", workflow_name="unknown", workflow_version="imported",
        params_json="{}", workflow_json="{}", source="imported",
    )
    db.update_generation("flux", output_files=json.dumps(
        [{"filename": "flux_t2i_upscaled_00004_.png", "subfolder": "image", "type": "output"}]
    ))
    assert backfill_unknown_workflows(db) == 1
    assert db.get_generation("flux")["workflow_name"] == "flux_t2i_upscaled"


def test_backfill_fills_flux_unet_from_stored_graph(tmp_path):
    # The same "unknown"-era Flux imports stored their graph but never pulled the
    # GGUF model into params, so they collapse under "(unknown model)" until the
    # backfill reads it back — the same repair the WAN dual-sampler test covers.
    db = Database(tmp_path / "test.db")
    graph = {
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "cyberrealisticFlux_v25GGUFQ80.gguf"}},
        "8": {"class_type": "KSampler", "inputs": {"seed": 1}},
    }
    db.insert_generation(
        prompt_id="flux-old", workflow_name="flux_t2i_upscaled", workflow_version="imported",
        params_json=json.dumps({"positive_prompt": "a portrait", "seed": 1}),
        workflow_json=json.dumps(graph), source="imported",
    )
    assert backfill_model_and_lora_params(db) == 1
    params = json.loads(db.get_generation("flux-old")["params_json"])
    assert params["unet"] == "cyberrealisticFlux_v25GGUFQ80.gguf"
    assert params["positive_prompt"] == "a portrait"   # existing params kept
    assert backfill_model_and_lora_params(db) == 0      # idempotent


def test_extract_metadata_identifies_wan22_t2i_from_graph(tmp_path):
    import origenerator.importer as imp
    # WAN 2.2 text-to-image embeds no Wan conditioning node and no checkpoint, so
    # its EmptyHunyuanLatentVideo + ImageFromBatch + SaveImage signature is what
    # names it. The filename matches no workflow prefix, proving the graph alone
    # suffices. Prompts come from the CLIPTextEncode titles, the seed from the
    # noise-adding (stage 1) sampler.
    graph = {
        "99": {"class_type": "CLIPTextEncode", "inputs": {"text": "a kitten"},
               "_meta": {"title": "CLIP Text Encode (Positive Prompt)"}},
        "91": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"},
               "_meta": {"title": "CLIP Text Encode (Negative Prompt)"}},
        "95": {"class_type": "KSamplerAdvanced",
               "inputs": {"noise_seed": 674502243979425, "add_noise": "disable"}},
        "96": {"class_type": "KSamplerAdvanced",
               "inputs": {"noise_seed": 746703007625838, "add_noise": "enable"}},
        "104": {"class_type": "EmptyHunyuanLatentVideo",
                "inputs": {"width": 1088, "height": 1920, "length": 5}},
        "117": {"class_type": "ImageFromBatch", "inputs": {"batch_index": 0, "length": 1}},
        "116": {"class_type": "SaveImage", "inputs": {"filename_prefix": "image/wan22_t2i"}},
    }
    _make_png_with_metadata(tmp_path / "renamed_99.png", graph)
    meta = imp._extract_metadata(tmp_path / "renamed_99.png", ".png")

    assert meta["workflow_name"] == "wan22_t2i"
    assert meta["positive_prompt"] == "a kitten"
    assert meta["negative_prompt"] == "blurry"
    assert meta["seed"] == 746703007625838   # stage-1 (add_noise enable) seed


def test_extract_metadata_reads_the_base_sampler_not_the_enhance_pass(tmp_path):
    import origenerator.importer as imp
    from origenerator.workflows import WORKFLOW_REGISTRY

    # An enhanced SDXL graph carries two KSamplers. A re-imported output must
    # record the recipe's base pass, not the low-denoise refinement the enhance
    # tail runs over its VAEEncode'd latent — otherwise the import would claim
    # the run took 20 steps at denoise 0.3.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    graph = wf.build_api_payload(dict(
        wf.default_params(), positive_prompt="a harbor at dawn", seed=4242,
        steps=50, enhance_steps=20, enhance_denoise=0.3,
    ))
    _make_png_with_metadata(tmp_path / "sdxl_t2i_00001_.png", graph)
    meta = imp._extract_metadata(tmp_path / "sdxl_t2i_00001_.png", ".png")

    assert meta["workflow_name"] == "sdxl_t2i"
    assert meta["positive_prompt"] == "a harbor at dawn"
    assert meta["seed"] == 4242
    assert meta["params"]["steps"] == 50
    assert meta["params"]["denoise"] == 1.0


# --- which workflow made this graph -------------------------------------------

def _graph_of(*class_types):
    """A minimal ComfyUI graph carrying nothing but these node classes."""
    return {str(i): {"class_type": name, "inputs": {}}
            for i, name in enumerate(class_types, start=1)}


# (the node classes in the graph, the workflow it must be read as). The chain is
# ORDERED, because a graph can satisfy more than one test: an flf2v graph also
# carries the i2v conditioning, a Flux one can also load a checkpoint. So the
# cases that matter are the ones naming the node that must LOSE beside the one
# that must win.
_READ_AS = (
    (("WanFirstLastFrameToVideo",), "wan22_flf2v_loop"),
    (("WanFirstLastFrameToVideo", "WanImageToVideo"), "wan22_flf2v_loop"),
    (("WanImageToVideo",), "wan22_i2v"),
    (("WanImageToVideo", "CheckpointLoaderSimple"), "wan22_i2v"),
    (("EmptyHunyuanLatentVideo", "SaveImage"), "wan22_t2i"),
    (("EmptyHunyuanLatentVideo", "SaveImage", "CheckpointLoaderSimple"), "wan22_t2i"),
    (("FluxGuidance",), "flux_t2i_upscaled"),
    (("UnetLoaderGGUF", "DualCLIPLoader"), "flux_t2i_upscaled"),
    (("FluxGuidance", "CheckpointLoaderSimple"), "flux_t2i_upscaled"),
    (("CheckpointLoaderSimple",), "sdxl_t2i"),
    # A video latent that was NOT saved as an image is not text-to-image, and a
    # GGUF UNET without the dual encoders is not Flux: both fall through, and
    # the filename's guess (none, for this name) stands.
    (("EmptyHunyuanLatentVideo",), "unknown"),
    (("UnetLoaderGGUF",), "unknown"),
    (("SomeNodeNobodyHasHeardOf",), "unknown"),
)


@pytest.mark.parametrize("node_types, expected", _READ_AS)
def test_the_graphs_nodes_name_the_workflow(tmp_path, node_types, expected):
    import origenerator.importer as imp

    # A filename matching no workflow prefix, so the graph alone decides.
    path = tmp_path / "renamed_00001_.png"
    _make_png_with_metadata(path, _graph_of(*node_types))

    assert imp._extract_metadata(path, ".png")["workflow_name"] == expected


def test_the_graph_overrules_what_the_filename_claimed(tmp_path):
    """The filename is a first guess only — a file renamed, or written under a
    prefix that was later reused, would otherwise be filed under the wrong
    workflow forever. Workflow names are persisted into every row and named from
    the overlay's recipes, so this is a data defect, not a display one."""
    import origenerator.importer as imp

    path = tmp_path / "sdxl_t2i_00001_.png"
    _make_png_with_metadata(path, _graph_of("WanImageToVideo"))

    assert imp._extract_metadata(path, ".png")["workflow_name"] == "wan22_i2v"


def test_a_graph_that_names_nothing_leaves_the_filenames_guess_standing(tmp_path):
    import origenerator.importer as imp

    path = tmp_path / "flux_t2i_upscaled_00001_.png"
    _make_png_with_metadata(path, _graph_of("SomeNodeNobodyHasHeardOf"))

    assert imp._extract_metadata(path, ".png")["workflow_name"] == "flux_t2i_upscaled"


def test_a_file_with_no_embedded_graph_keeps_the_filenames_guess(tmp_path):
    import origenerator.importer as imp

    path = tmp_path / "wan22_t2i_00001_.png"
    Image.new("RGB", (8, 8)).save(path)

    meta = imp._extract_metadata(path, ".png")

    assert meta["workflow_name"] == "wan22_t2i"
    assert meta["prompt_data"] == {}
    assert meta["params"] == {}
