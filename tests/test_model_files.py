import os

from origenerator import config
from origenerator.workflows.model_files import (
    NO_LORA, is_no_lora, list_detector_files, list_lora_files, list_model_files,
)


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


def test_is_no_lora_recognizes_the_sentinel_and_empty_values():
    # A bypassed LoRA reads the same however it was recorded: the "None" sentinel
    # a generation stores, or the empty/absent value an older row or a no-LoRA
    # import carries.
    assert is_no_lora(NO_LORA)
    assert is_no_lora("")
    assert is_no_lora(None)
    assert not is_no_lora("real_lora.safetensors")
