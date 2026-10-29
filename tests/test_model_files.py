from __future__ import annotations

import inspect
import os
import struct

import pytest

from origenerator import config
from origenerator.workflows import model_files
from origenerator.workflows.model_arch import FLUX, SD15, SDXL, WAN, WAN_T2V
from origenerator.workflows.model_files import (
    ANY,
    NO_LORA,
    is_no_lora,
    list_detector_files,
    list_lora_files,
    list_model_files,
    list_outline_detector_files,
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


def test_a_picker_lists_its_files_in_the_order_of_their_titles(tmp_path, monkeypatch,
                                                              titled_models):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    loras = tmp_path / "models" / "loras"
    loras.mkdir(parents=True)
    (loras / "a_style.safetensors").touch()
    (loras / "b_style.safetensors").touch()
    titled_models({"a_style": "Zebra Style", "b_style": "apple style"})

    assert list_model_files("loras", [], accepts=ANY) == [
        "b_style.safetensors", "a_style.safetensors"]


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


def test_a_models_folder_nothing_has_changed_in_is_not_walked_again(installed_models, monkeypatch):
    # Every picker of every form listed its folder afresh -- a walk of the whole
    # folder and a stat of every model in it -- which the first draw of a window
    # paid some thirty times over for folders that change once a month.
    installed_models.add("checkpoints", "a.safetensors", arch=SDXL)
    walks = []
    walk = model_files._model_paths
    monkeypatch.setattr(model_files, "_model_paths",
                        lambda directory: walks.append(directory) or walk(directory))

    first = model_files.list_model_files("checkpoints", [], accepts=SDXL)
    again = model_files.list_model_files("checkpoints", [], accepts=SDXL)
    other_picker = model_files.list_model_files("checkpoints", [], accepts=ANY)

    assert first == again == other_picker == ["a.safetensors"]
    assert len(walks) == 1


def test_a_model_added_to_its_folder_is_listed_without_a_restart(installed_models):
    installed_models.add("checkpoints", "a.safetensors", arch=SDXL)
    assert model_files.list_model_files("checkpoints", [], accepts=SDXL) == ["a.safetensors"]

    installed_models.add("checkpoints", "b.safetensors", arch=SDXL)

    assert model_files.list_model_files("checkpoints", [], accepts=SDXL) == [
        "a.safetensors", "b.safetensors"]


def test_a_model_taken_out_of_its_folder_is_no_longer_listed(installed_models):
    kept = installed_models.add("checkpoints", "a.safetensors", arch=SDXL)
    gone = installed_models.add("checkpoints", "b.safetensors", arch=SDXL)
    assert len(model_files.list_model_files("checkpoints", [], accepts=SDXL)) == 2

    gone.unlink()

    assert model_files.list_model_files("checkpoints", [], accepts=SDXL) == [kept.name]


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


def test_a_lora_picker_whose_default_is_none_offers_none_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)  # no LoRA installed at all
    assert list_lora_files([NO_LORA], accepts=(WAN,)) == [NO_LORA]


def test_the_detail_passs_detectors_come_from_the_ultralytics_bbox_dir(tmp_path, monkeypatch):
    # Where the detail pass's provider node looks for them. Empty rather than a
    # fallback name: "no detector installed" is a real state the panel has to be
    # able to read, and a fabricated default would hide it under a failed submit.
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


def test_a_wan_lora_civitai_files_under_text_to_video_is_a_text_to_video_lora(
        installed_models, recorded_base_models):
    for stem in ("made_for_t2v", "made_for_i2v", "not_on_civitai"):
        installed_models.add("loras", f"{stem}.safetensors", arch=WAN, lora=True)
    recorded_base_models({"made_for_t2v": "Wan Video 2.2 T2V-A14B",
                          "made_for_i2v": "Wan Video 14B i2v 480p"})

    assert list_lora_files([], accepts=(WAN,)) == [
        NO_LORA, "made_for_i2v.safetensors", "not_on_civitai.safetensors"]
    assert list_lora_files([], accepts=(WAN_T2V,)) == [NO_LORA, "made_for_t2v.safetensors"]


def test_a_fixs_lora_is_offered_only_by_the_picker_of_that_fix(installed_models):
    mouth = os.path.join("fixes", "mouth 2026-10-19 1444.safetensors")
    for name in ("a_look.safetensors", mouth, os.path.join("fixes", "faces 2026-10-20 0910.safetensors"),
                 os.path.join("fixes", "named_by_hand.safetensors")):
        installed_models.add("loras", name, arch=SDXL, lora=True)

    assert list_lora_files([], accepts=(SDXL,)) == [NO_LORA, "a_look.safetensors"]
    assert list_lora_files([], accepts=(SDXL,), fix="mouth") == [
        NO_LORA, "a_look.safetensors", mouth]


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


def test_the_detectors_that_draw_outlines_come_from_the_ultralytics_segm_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    assert list_outline_detector_files() == []

    segm = tmp_path / "models" / "ultralytics" / "segm"
    segm.mkdir(parents=True)
    (segm / "skin_finder.pt").touch()
    assert list_outline_detector_files() == ["skin_finder.pt"]
