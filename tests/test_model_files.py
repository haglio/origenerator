import inspect
import os
import struct

import pytest

from origenerator import config
from origenerator.workflows.model_arch import FLUX, SD15, SDXL, WAN
from origenerator.workflows.model_files import (
    ANY, NO_LORA, is_no_lora, list_detector_files, list_lora_files, list_model_files,
)


def test_lists_sorted_model_files_from_the_category_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    loras = tmp_path / "models" / "loras"
    loras.mkdir(parents=True)
    (loras / "b.safetensors").touch()
    (loras / "a.safetensors").touch()
    (loras / "notes.txt").touch()   # not a model file — skipped
    assert list_model_files("loras", ["fallback.safetensors"], accepts=ANY) == [
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
    assert list_model_files("diffusion_models", ["fb.safetensors"], accepts=ANY) == [
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
    assert list_model_files("diffusion_models", ["fb.safetensors"], accepts=ANY) == [
        os.path.join("split_files", "deep.safetensors"), "top.safetensors",
    ]


def test_falls_back_when_the_category_dir_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)  # no models/loras at all
    assert list_model_files("loras", ["default.safetensors"], accepts=ANY) == [
        "default.safetensors",
    ]


def test_falls_back_when_the_category_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    (tmp_path / "models" / "loras").mkdir(parents=True)
    assert list_model_files("loras", ["default.safetensors"], accepts=ANY) == [
        "default.safetensors",
    ]


def test_lora_picker_leads_with_the_none_sentinel(installed_models):
    # A LoRA is optional: the picker offers "None" first (which the workflow
    # builds with no LoraLoader, running the base model unmodified), then the
    # installed files from the same scan as any model picker.
    installed_models.add("loras", "b.safetensors", arch=WAN, lora=True)
    installed_models.add("loras", "a.safetensors", arch=WAN, lora=True)
    assert list_lora_files(["fallback.safetensors"], accepts=(WAN,)) == [
        NO_LORA, "a.safetensors", "b.safetensors",
    ]
    assert NO_LORA not in list_model_files("loras", ["fallback.safetensors"], accepts=ANY)


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


def test_a_picker_offers_only_the_architectures_its_graph_runs(installed_models):
    # models/checkpoints is a folder, not a catalogue: WAN's high/low expert
    # pairs and LTX land there beside the SDXL checkpoints, carrying no text
    # encoder for an SDXL graph's CLIPTextEncode to read. Offering the pair asks
    # the user to choose between two runs that can only error.
    installed_models.add("checkpoints", "an_xl_model.safetensors", arch=SDXL)
    installed_models.add("checkpoints", "a_15_model.safetensors", arch=SD15)
    installed_models.add("checkpoints", "vid_high.safetensors", arch=WAN)
    installed_models.add("checkpoints", "vid_low.safetensors", arch=WAN)
    installed_models.add("checkpoints", "some_flux.safetensors", arch=FLUX)
    assert list_model_files("checkpoints", ["fb.safetensors"], accepts=(SDXL, SD15)) == [
        "a_15_model.safetensors", "an_xl_model.safetensors",
    ]


def test_a_picker_keeps_what_it_could_not_classify(installed_models):
    # Dropping a model that works is the costly mistake; keeping one that
    # doesn't is not. A file with no readable index — a .ckpt, one truncated
    # mid-header, an architecture postdating these signatures — stays listed.
    installed_models.add("checkpoints", "old.ckpt", body=b"pickled weights, no header")
    installed_models.add("checkpoints", "cut.safetensors", body=struct.pack("<Q", 4096) + b"{}")
    installed_models.add("checkpoints", "future.safetensors", arch=None)
    installed_models.add("checkpoints", "vid.safetensors", arch=WAN)
    assert list_model_files("checkpoints", ["fb.safetensors"], accepts=(SDXL,)) == [
        "cut.safetensors", "future.safetensors", "old.ckpt",
    ]


def test_a_picker_drops_the_other_half_of_the_expert_pair(installed_models):
    # WAN 2.2 splits into a high-noise and a low-noise expert, and the workflow
    # has a slot for each. A file naming the other half is the one pick that is
    # certainly wrong; a file naming neither stays in both, because nothing
    # inside a WAN 2.2 file tells the two experts apart.
    for name in ("wan_high_noise.safetensors", "wan_low_noise.safetensors",
                 "wan_unmarked.safetensors"):
        installed_models.add("diffusion_models", name, arch=WAN)
    assert list_model_files("diffusion_models", ["fb"], accepts=(WAN,), expert="high") == [
        "wan_high_noise.safetensors", "wan_unmarked.safetensors",
    ]
    assert list_model_files("diffusion_models", ["fb"], accepts=(WAN,), expert="low") == [
        "wan_low_noise.safetensors", "wan_unmarked.safetensors",
    ]


def test_a_model_picker_and_a_lora_picker_do_not_offer_each_other(installed_models):
    # Both folders hold the wrong kind — a WAN LoRA filed under
    # diffusion_models, a full checkpoint filed under loras — and neither loads
    # in the other's slot, whatever architecture it was trained for.
    installed_models.add("diffusion_models", "real_model.safetensors", arch=WAN)
    installed_models.add("diffusion_models", "stray_lora.safetensors", arch=WAN, lora=True)
    installed_models.add("loras", "real_lora.safetensors", arch=WAN, lora=True)
    installed_models.add("loras", "stray_model.safetensors", arch=WAN)
    assert list_model_files("diffusion_models", ["fb"], accepts=(WAN,)) == [
        "real_model.safetensors",
    ]
    assert list_lora_files(["fb"], accepts=(WAN,)) == [NO_LORA, "real_lora.safetensors"]


def test_a_picker_drops_the_parts_of_a_sharded_download(installed_models):
    installed_models.add("diffusion_models", "whole.safetensors", arch=WAN)
    for part in (1, 2, 3):
        installed_models.add(
            "diffusion_models", f"model-0000{part}-of-00003.safetensors", arch=WAN,
        )
    assert list_model_files("diffusion_models", ["fb"], accepts=(WAN,)) == [
        "whole.safetensors",
    ]


def test_filtering_never_empties_a_dropdown(installed_models):
    # A folder holding nothing this graph can run still offers the workflow's
    # own default, so the form always has something selected.
    installed_models.add("checkpoints", "vid_high.safetensors", arch=WAN)
    assert list_model_files("checkpoints", ["default.safetensors"], accepts=(SDXL,)) == [
        "default.safetensors",
    ]


def test_listing_a_folder_requires_saying_what_the_graph_runs():
    # The enforcement, and the reason `accepts` is keyword-only with no default:
    # a workflow added later cannot list a category without answering the
    # question. Forgetting is a TypeError at the call, not a dropdown that
    # quietly went back to offering everything. ANY is how a genuinely
    # architecture-neutral category (the ESRGAN upscalers) says so out loud.
    for picker in (list_model_files, list_lora_files):
        accepts = inspect.signature(picker).parameters["accepts"]
        assert accepts.kind is inspect.Parameter.KEYWORD_ONLY, picker.__name__
        assert accepts.default is inspect.Parameter.empty, picker.__name__

    with pytest.raises(TypeError):
        list_model_files("checkpoints", ["fb.safetensors"])
    with pytest.raises(TypeError):
        list_lora_files(["fb.safetensors"])


def test_is_no_lora_recognizes_the_sentinel_and_empty_values():
    # A bypassed LoRA reads the same however it was recorded: the "None" sentinel
    # a generation stores, or the empty/absent value an older row or a no-LoRA
    # import carries.
    assert is_no_lora(NO_LORA)
    assert is_no_lora("")
    assert is_no_lora(None)
    assert not is_no_lora("real_lora.safetensors")
