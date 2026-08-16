import json
import os
import struct

from origenerator import config
from origenerator.workflows.model_files import (
    NO_LORA, is_no_lora, list_checkpoint_files, list_detector_files, list_lora_files,
    list_model_files,
)

# Stand-in tensor names for the three shapes the checkpoints folder holds: SDXL
# (two CLIPs under ``conditioner.``), SD1.5 (one under ``cond_stage_model.``),
# and a diffusion-only file like WAN 2.2's high/low experts, which ships weights
# and a VAE but no text encoder at all.
_SDXL_KEYS = ["conditioner.embedders.0.transformer.text_model.x", "model.diffusion_model.y"]
_SD15_KEYS = ["cond_stage_model.transformer.text_model.x", "model.diffusion_model.y"]
_DIFFUSION_ONLY_KEYS = ["model.diffusion_model.blocks.0.x", "vae.decoder.y"]


def _write_safetensors(path, keys):
    """A real-enough safetensors file: the little-endian u64 header length, then
    the JSON header naming *keys*. No tensor data — the picker reads the header
    and stops, so that is the whole file the test needs.
    """
    header = json.dumps(
        {key: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for key in keys}
    ).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")


def test_lists_sorted_model_files_from_the_category_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    loras = tmp_path / "models" / "loras"
    loras.mkdir(parents=True)
    (loras / "b.safetensors").touch()
    (loras / "a.safetensors").touch()
    (loras / "notes.txt").touch()   # not a model file — skipped
    assert list_model_files("loras", ["fallback.safetensors"]) == [
        "a.safetensors", "b.safetensors",
    ]


def test_lists_gguf_models(tmp_path, monkeypatch):
    # Flux runs on GGUF-quantized diffusion models (loaded by UnetLoaderGGUF), so
    # the Model picker must list them alongside the .safetensors it already finds.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    diffusion = tmp_path / "models" / "diffusion_models"
    diffusion.mkdir(parents=True)
    (diffusion / "flux.gguf").touch()
    (diffusion / "wan.safetensors").touch()
    assert list_model_files("diffusion_models", ["fb.safetensors"]) == [
        "flux.gguf", "wan.safetensors",
    ]


def test_lists_nested_model_files_with_relative_paths(tmp_path, monkeypatch):
    # ComfyUI's loaders list models in subfolders too, naming them by the path
    # relative to the category dir (e.g. WAN's split_files/…). The picker must
    # match, so a nested model is selectable and its stored value round-trips.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    diffusion = tmp_path / "models" / "diffusion_models"
    (diffusion / "split_files").mkdir(parents=True)
    (diffusion / "top.safetensors").touch()
    (diffusion / "split_files" / "deep.safetensors").touch()
    assert list_model_files("diffusion_models", ["fb.safetensors"]) == [
        os.path.join("split_files", "deep.safetensors"), "top.safetensors",
    ]


def test_falls_back_when_the_category_dir_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)  # no models/loras at all
    assert list_model_files("loras", ["default.safetensors"]) == ["default.safetensors"]


def test_falls_back_when_the_category_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    (tmp_path / "models" / "loras").mkdir(parents=True)
    assert list_model_files("loras", ["default.safetensors"]) == ["default.safetensors"]


def test_lora_picker_leads_with_the_none_sentinel(tmp_path, monkeypatch):
    # A LoRA is optional: the picker offers "None" first (which the workflow
    # builds with no LoraLoader, running the base model unmodified), then the
    # installed files from the same scan as any model picker.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    loras = tmp_path / "models" / "loras"
    loras.mkdir(parents=True)
    (loras / "b.safetensors").touch()
    (loras / "a.safetensors").touch()
    assert list_lora_files(["fallback.safetensors"]) == [
        NO_LORA, "a.safetensors", "b.safetensors",
    ]
    assert NO_LORA not in list_model_files("loras", ["fallback.safetensors"])


def test_the_detail_passs_detectors_come_from_the_ultralytics_bbox_dir(tmp_path, monkeypatch):
    # Where the detail pass's provider node looks for them. Empty rather than a
    # fallback name: "no detector installed" is a real state the panel has to be
    # able to read, and a fabricated default would hide it behind a failed submit.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    assert list_detector_files() == []

    bbox = tmp_path / "models" / "ultralytics" / "bbox"
    bbox.mkdir(parents=True)
    (bbox / "hand_finder.pt").touch()
    (bbox / "face_finder.pt").touch()
    assert list_detector_files() == ["face_finder.pt", "hand_finder.pt"]


def test_checkpoint_picker_drops_the_files_carrying_no_text_encoder(tmp_path, monkeypatch):
    # The checkpoints folder is mixed: WAN 2.2's high/low pair lands there beside
    # the SD1.5/SDXL checkpoints, carrying no text encoder for the SDXL graphs'
    # CLIPTextEncode to read. Offering either half asks the user to choose
    # between two runs that can only error.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    checkpoints = tmp_path / "models" / "checkpoints"
    checkpoints.mkdir(parents=True)
    _write_safetensors(checkpoints / "an_xl_model.safetensors", _SDXL_KEYS)
    _write_safetensors(checkpoints / "a_15_model.safetensors", _SD15_KEYS)
    _write_safetensors(checkpoints / "vid_high.safetensors", _DIFFUSION_ONLY_KEYS)
    _write_safetensors(checkpoints / "vid_low.safetensors", _DIFFUSION_ONLY_KEYS)
    assert list_checkpoint_files(["fallback.safetensors"]) == [
        "a_15_model.safetensors", "an_xl_model.safetensors",
    ]


def test_checkpoint_picker_keeps_what_it_cannot_read_a_header_from(tmp_path, monkeypatch):
    # Dropping a checkpoint that works is the costly mistake; keeping one that
    # doesn't is not. So a file with no readable safetensors header — a .ckpt, or
    # one truncated mid-header — stays listed rather than being judged.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    checkpoints = tmp_path / "models" / "checkpoints"
    checkpoints.mkdir(parents=True)
    (checkpoints / "old.ckpt").write_bytes(b"pickled weights, no header")
    (checkpoints / "truncated.safetensors").write_bytes(struct.pack("<Q", 4096) + b"{}")
    (checkpoints / "empty.safetensors").write_bytes(b"")
    assert list_checkpoint_files(["fallback.safetensors"]) == [
        "empty.safetensors", "old.ckpt", "truncated.safetensors",
    ]


def test_checkpoint_picker_falls_back_when_nothing_qualifies(tmp_path, monkeypatch):
    # Filtering must not empty the dropdown: a folder of nothing but
    # diffusion-only files still offers the workflow's own default.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    checkpoints = tmp_path / "models" / "checkpoints"
    checkpoints.mkdir(parents=True)
    _write_safetensors(checkpoints / "vid_high.safetensors", _DIFFUSION_ONLY_KEYS)
    assert list_checkpoint_files(["default.safetensors"]) == ["default.safetensors"]


def test_checkpoint_picker_matches_text_encoder_keys_only_at_a_name_start(tmp_path, monkeypatch):
    # The header is matched as raw bytes, so the prefixes carry their opening
    # quote: a diffusion-only file whose tensor names merely contain the word
    # must not read as shipping a text encoder.
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    checkpoints = tmp_path / "models" / "checkpoints"
    checkpoints.mkdir(parents=True)
    _write_safetensors(
        checkpoints / "vid.safetensors", ["model.diffusion_model.conditioner.proj"],
    )
    assert list_checkpoint_files(["default.safetensors"]) == ["default.safetensors"]


def test_is_no_lora_recognizes_the_sentinel_and_empty_values():
    # A bypassed LoRA reads the same however it was recorded: the "None" sentinel
    # a generation stores, or the empty/absent value an older row or a no-LoRA
    # import carries.
    assert is_no_lora(NO_LORA)
    assert is_no_lora("")
    assert is_no_lora(None)
    assert not is_no_lora("real_lora.safetensors")
