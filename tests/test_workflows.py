from __future__ import annotations

import json
import re

import pytest
from PIL import Image

import origenerator.workflows.derived_size as ds
import origenerator.workflows.detail_parts as detail_module
import origenerator.workflows.lora_rows as lora_rows_module
import origenerator.workflows.model_dropdowns as dropdowns
from origenerator import config, points_of_interest
from origenerator.box_breaks import BOX_BREAK
from origenerator.comfy_graph import dual_sampler_model_files, graph_model_params, texts_read
from origenerator.gui.param_fields import clamped_number
from origenerator.importer import _GRAPH_SIGNATURES, _workflow_from_nodes
from origenerator.media import MediaType
from origenerator.workflows import (
    RETIRED_WORKFLOW_NAMES,
    WORKFLOW_REGISTRY,
    base,
    offered_workflows,
    workflow_named,
)
from origenerator.workflows.base import (
    DURATION_OPTIONS,
    RIFE_CHECKPOINT,
    SINGLE_WINDOW_FRAMES,
    ParamDef,
    WorkflowTemplate,
    chained_to,
)
from origenerator.workflows.derived_size import scale_to_total_pixels
from origenerator.workflows.duration import seconds_for_frames
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    playback_rate,
)
from origenerator.workflows.image_enhance import ImageEnhanceWorkflow
from origenerator.workflows.krea2_t2i import Krea2T2iWorkflow
from origenerator.workflows.model_files import NO_LORA
from origenerator.workflows.outside import VideoKind, outside_workflow
from origenerator.workflows.sdxl_pose_transfer import SdxlPoseTransferWorkflow
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow
from origenerator.workflows.wan22_t2i import Wan22T2iWorkflow


def _find_node(payload: dict, class_type: str) -> dict | None:
    for node in payload.values():
        if node.get("class_type") == class_type:
            return node
    return None


def _node_id(payload: dict, class_type: str) -> str | None:
    for node_id, node in payload.items():
        if node.get("class_type") == class_type:
            return node_id
    return None


_VIDEO_WORKFLOWS = [
    n for n, wf in WORKFLOW_REGISTRY.items() if wf.output_type == "video"
]
_SCORED_VIDEO_WORKFLOWS = [
    n for n in _VIDEO_WORKFLOWS if "audio_prompt" in WORKFLOW_REGISTRY[n].default_params()
]


def test_workflows_declare_the_params_that_identify_their_model():
    assert SdxlT2iWorkflow().model_keys == ("checkpoint",)
    assert Wan22I2vWorkflow().model_keys == ("unet_high", "unet_low")
    assert Wan22Flf2vLoopWorkflow().model_keys == ("unet_high", "unet_low")


def test_workflows_declare_the_params_that_identify_their_lora():
    assert Wan22I2vWorkflow().lora_keys == ("lora_high", "lora_high_2", "lora_high_3",
                                            "lora_low", "lora_low_2", "lora_low_3")
    assert Wan22Flf2vLoopWorkflow().lora_keys == Wan22I2vWorkflow().lora_keys
    assert FluxT2iUpscaledWorkflow().lora_keys == ("lora", "lora_2", "lora_3")
    assert SdxlT2iWorkflow().lora_keys == ("lora", "lora_2", "lora_3")
    assert Wan22T2iWorkflow().lora_keys == ()


def test_only_the_flf2v_workflow_declares_itself_looping():
    assert Wan22Flf2vLoopWorkflow().looping is True
    assert Wan22I2vWorkflow().looping is False
    assert SdxlT2iWorkflow().looping is False


def test_wan_video_workflows_expose_lora_pickers(monkeypatch):
    options = [NO_LORA, "x_high.safetensors", "y_low.safetensors"]
    monkeypatch.setattr(lora_rows_module, "list_lora_files", lambda fallback, **terms: options)

    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        for level in ("high", "low"):
            dropdown = by_key[f"lora_{level}"]
            assert dropdown.type == "dropdown"
            assert dropdown.options == options
            assert dropdown.options[0] == NO_LORA
            assert dropdown.default == wf.default_params()[f"lora_{level}"]


def test_wan_video_workflows_bypass_a_none_lora(monkeypatch):
    def lora_count(payload):
        return sum(n["class_type"] == "LoraLoaderModelOnly" for n in payload.values())

    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        base = dict(wf.default_params(), lora_high="hi.safetensors", lora_low="lo.safetensors")

        both = wf.build_api_payload(base)
        assert lora_count(both) == 2
        read = dual_sampler_model_files(both)
        assert read["lora_high"] == "hi.safetensors"
        assert read["lora_low"] == "lo.safetensors"

        high_off = wf.build_api_payload(dict(base, lora_high=NO_LORA))
        assert lora_count(high_off) == 1
        read = dual_sampler_model_files(high_off)
        assert "lora_high" not in read
        assert read["lora_low"] == "lo.safetensors"
        assert read["unet_high"] == base["unet_high"]

        none = wf.build_api_payload(dict(base, lora_high=NO_LORA, lora_low=NO_LORA))
        assert lora_count(none) == 0
        read = dual_sampler_model_files(none)
        assert "lora_high" not in read
        assert "lora_low" not in read
        assert read["unet_high"] == base["unet_high"]
        assert read["unet_low"] == base["unet_low"]


def test_wan_video_workflows_expose_model_dropdowns(monkeypatch):
    installed = {
        "diffusion_models": ["m_high.safetensors", "m_low.safetensors"],
        "loras": ["l.safetensors"],
    }
    def dropdown(category, fallback, **terms):
        return installed[category]
    monkeypatch.setattr(dropdowns, "list_model_files", dropdown)

    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        for level in ("high", "low"):
            model = by_key[f"unet_{level}"]
            assert model.type == "dropdown"
            assert model.options == installed["diffusion_models"]
            assert model.default == wf.default_params()[f"unet_{level}"]


def test_wan_video_workflows_group_all_models_then_all_loras():
    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        keys = [d.key for d in wf.param_definitions()]
        model_block = [keys.index(k) for k in ("unet_high", "unet_low")]
        lora_block = [index for index, key in enumerate(keys) if key.startswith("lora")]
        assert model_block == list(range(model_block[0], model_block[0] + 2))
        assert lora_block == list(range(lora_block[0], lora_block[0] + len(lora_block)))
        assert model_block[-1] < lora_block[0]


def test_the_two_wan_expert_pair_workflows_offer_one_and_the_same_pair(installed_models):
    for expert in ("high", "low"):
        installed_models.add("diffusion_models", f"wan_{expert}_noise.safetensors", arch="wan")
        installed_models.add("loras", f"wan_{expert}_lora.safetensors", arch="wan", lora=True)

    pair_keys = ("unet_high", "unet_low", "lora_high", "lora_strength_high",
                 "lora_low", "lora_strength_low")
    shapes = []
    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {d.key: d for d in wf.param_definitions()}
        shapes.append([
            (key, by_key[key].label, by_key[key].type, by_key[key].options,
             by_key[key].min_val, by_key[key].max_val, by_key[key].step)
            for key in pair_keys
        ])
    assert shapes[0] == shapes[1]
    assert "wan_high_noise.safetensors" in dict(zip(pair_keys, shapes[0], strict=True))["unet_high"][3]


def test_workflows_expose_their_seed_param_keys():
    assert SdxlT2iWorkflow().seed_keys() == ("seed",)
    assert Wan22I2vWorkflow().seed_keys() == ("noise_seed", "audio_seed"), (
        "a variation's motion changes, so its sound is scored again too: the old track could not fit")
    assert Wan22Flf2vLoopWorkflow().seed_keys() == ("noise_seed", "audio_seed")


def test_a_workflow_names_its_seed_fields_building_its_form_once(monkeypatch):
    builds = []
    real = Wan22I2vWorkflow.param_definitions
    monkeypatch.setattr(Wan22I2vWorkflow, "param_definitions",
                        lambda self: builds.append(self) or real(self))
    workflow = Wan22I2vWorkflow()

    assert workflow.seed_keys() == workflow.seed_keys() == ("noise_seed", "audio_seed")
    assert len(builds) == 1


def test_only_the_video_workflows_go_on_drawing_seeds_once_one_is_reused():
    pinning = {name for name, wf in WORKFLOW_REGISTRY.items() if wf.pins_reused_seed()}
    drawing = set(WORKFLOW_REGISTRY) - pinning
    assert drawing == {"wan22_i2v", "wan22_flf2v_loop", "wan22_animate"}, (
        "a video's seed is only one sample of its motion, and pinned it would ride every prompt "
        "edit out of that line of videos, so reusing its settings draws another")
    assert {"sdxl_t2i", "wan22_t2i", "flux_t2i_upscaled"} <= pinning, (
        "an image's seed is its composition, the point of editing one, so reusing its settings keeps it")
    assert all(WORKFLOW_REGISTRY[n].output_type == "video" for n in drawing)
    assert all(WORKFLOW_REGISTRY[n].output_type == "image" for n in pinning)


def test_wan_video_workflows_expose_editable_audio_params():
    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        prompt = by_key["audio_prompt"]
        assert prompt.type == "str"
        assert prompt.multiline
        assert prompt.default == ""
        negative = by_key["audio_negative_prompt"]
        assert negative.type == "str"
        assert negative.multiline
        assert negative.default == "noisy, harsh"
        assert by_key["audio_seed"].type == "seed"
        assert "foley_model" not in by_key


def test_sdxl_t2i_default_params_has_required_keys():
    wf = SdxlT2iWorkflow()
    params = wf.default_params()
    required = {
        "positive_prompt", "negative_prompt", "seed", "steps", "cfg",
        "width", "height", "sampler_name", "scheduler", "denoise",
    }
    assert required.issubset(params.keys())


def test_every_sdxl_t2i_setting_is_declared_as_a_paramdef():
    wf = SdxlT2iWorkflow()
    defs = wf.param_definitions()
    assert len(defs) > 0
    assert all(isinstance(d, ParamDef) for d in defs)
    keys = [d.key for d in defs]
    assert "positive_prompt" in keys
    assert "seed" in keys


def test_a_setting_of_a_kind_no_form_can_edit_is_refused_where_it_is_declared():
    with pytest.raises(ValueError, match="'integer' is not a valid ParamType"):
        ParamDef("steps", "Steps", "integer", 20)


def test_sdxl_t2i_build_api_payload_structure():
    wf = SdxlT2iWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "test prompt"
    params["negative_prompt"] = "bad quality"
    params["seed"] = 42
    payload = wf.build_api_payload(params)
    assert isinstance(payload, dict)
    assert payload["2"]["class_type"] == "CLIPTextEncode"
    assert payload["2"]["inputs"]["text"] == "test prompt"
    assert payload["3"]["inputs"]["text"] == "bad quality"
    assert payload["5"]["class_type"] == "KSampler"
    assert payload["5"]["inputs"]["seed"] == 42
    assert payload["5"]["inputs"]["steps"] == params["steps"]
    assert payload["5"]["inputs"]["cfg"] == params["cfg"]
    assert payload["7"]["class_type"] == "SaveImage"


@pytest.mark.parametrize("name", ["sdxl_t2i", "sdxl_pose_transfer", "krea2_t2i"])
def test_an_image_drawn_from_nothing_is_always_drawn_fully(name):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(wf.default_params(), input_image="x.png", denoise=0.4))

    latent_id = _node_id(payload, "EmptyLatentImage")
    sampler = next(n for n in payload.values() if n["class_type"] == "KSampler"
                   and n["inputs"]["latent_image"] == [latent_id, 0])
    assert sampler["inputs"]["denoise"] == 1.0
    assert "denoise" not in {pd.key for pd in wf.param_definitions()}


def test_sdxl_t2i_extract_output_info():
    wf = SdxlT2iWorkflow()
    history = {
        "outputs": {
            "7": {
                "images": [
                    {"filename": "sdxl_t2i_00001_.png", "subfolder": "image", "type": "output"}
                ]
            }
        }
    }
    files = wf.extract_output_info(history)
    assert len(files) == 1
    assert files[0]["filename"] == "sdxl_t2i_00001_.png"


_ENHANCE_TOGGLE_WORKFLOWS = ("sdxl_t2i", "sdxl_pose_transfer",
                             "flux_t2i_upscaled", "wan22_t2i", "krea2_t2i")


def test_image_workflows_carry_the_enhance_toggle_off_by_default():
    for name in _ENHANCE_TOGGLE_WORKFLOWS:
        wf = WORKFLOW_REGISTRY[name]
        toggle = {pd.key: pd for pd in wf.param_definitions()}["enhance"]
        assert toggle.type == "bool", name
        assert toggle.default is False, (
            f"{name}: enhancing is a layer the gallery adds afterward, which keeps the original "
            "and names every version, where a tail baked in here would leave neither")
        assert wf.default_params()["enhance"] is False, name


def test_enhance_toggle_appends_the_tail_on_every_image_workflow():
    for name in _ENHANCE_TOGGLE_WORKFLOWS:
        wf = WORKFLOW_REGISTRY[name]
        params = dict(wf.default_params(), seed=11, enhance=True,
                      enhance_scale=2.0, enhance_steps=17, enhance_denoise=0.35)
        payload = wf.build_api_payload(params)

        loader_id = _node_id(payload, "UpscaleModelLoader")
        assert payload[loader_id]["inputs"]["model_name"] == params["upscale_model"], name
        up_id = _node_id(payload, "ImageUpscaleWithModel")
        assert payload[up_id]["inputs"]["upscale_model"] == [loader_id, 0]
        scale_id = _node_id(payload, "ImageScaleBy")
        assert scale_id is not None, (
            f"{name}: its width and height fields are the base render's, and an enhance "
            "rescaled to them would come out the base render's size")
        scale = payload[scale_id]["inputs"]
        assert scale["image"] == [up_id, 0]
        assert scale["scale_by"] == pytest.approx(2.0 / 4.0)
        encode_id = _node_id(payload, "VAEEncode")
        assert payload[encode_id]["inputs"]["pixels"] == [scale_id, 0]

        sampler = next(n for n in payload.values()
                       if n["class_type"] == "KSampler"
                       and n["inputs"]["latent_image"] == [encode_id, 0])
        sampler_id = next(k for k, v in payload.items() if v is sampler)
        assert sampler["inputs"]["steps"] == 17, (
            f"{name}: no form sets the switch any more, but a run that recorded an enhance "
            "has to reproduce exactly what it recorded")
        assert sampler["inputs"]["denoise"] == 0.35
        assert sampler["inputs"]["seed"] == 11
        assert sampler["inputs"]["cfg"] == params["cfg"]

        save = _find_node(payload, "SaveImage")
        final = payload[save["inputs"]["images"][0]]
        assert final["class_type"] == "VAEDecode", name
        assert final["inputs"]["samples"] == [sampler_id, 0], (
            f"{name}: the base render is saved after it, so the first save in the graph "
            "is still the image the run is for")
        assert final["inputs"]["vae"] == payload[encode_id]["inputs"]["vae"]


def test_enhance_toggle_off_ends_at_the_plain_output():
    for name in _ENHANCE_TOGGLE_WORKFLOWS:
        wf = WORKFLOW_REGISTRY[name]
        payload = wf.build_api_payload(dict(wf.default_params(), enhance=False))
        assert _find_node(payload, "VAEEncode") is None, name
        assert _find_node(payload, "ImageScaleBy") is None, name
        saved = _find_node(payload, "SaveImage")["inputs"]["images"]
        if name == "flux_t2i_upscaled":
            assert saved == [_node_id(payload, "ImageUpscaleWithModel"), 0]
        else:
            assert _find_node(payload, "ImageUpscaleWithModel") is None, name
            assert payload[saved[0]]["class_type"] in ("VAEDecode", "ImageFromBatch"), name


def test_wan22_t2i_enhances_on_its_low_noise_refinement_chain():
    wf = WORKFLOW_REGISTRY["wan22_t2i"]
    payload = wf.build_api_payload(dict(wf.default_params(), enhance=True))
    encode_id = _node_id(payload, "VAEEncode")
    (sampler,) = _nodes_of(payload, "KSampler")
    assert sampler["inputs"]["latent_image"] == [encode_id, 0], (
        "the WAN VAE gives the kept frame back as a one-frame video, "
        "the very shape the still's own passes denoise")
    low = next(n for n in payload.values()
               if n["class_type"] == "KSamplerAdvanced"
               and n["inputs"]["add_noise"] == "disable")
    assert sampler["inputs"]["model"] == low["inputs"]["model"]
    assert sampler["inputs"]["positive"] == low["inputs"]["positive"]
    assert sampler["inputs"]["negative"] == low["inputs"]["negative"]
    frame_id = _node_id(payload, "ImageFromBatch")
    assert _find_node(payload, "ImageUpscaleWithModel")["inputs"]["image"] == [frame_id, 0]


def test_flux_enhance_resamples_on_the_guided_conditioning():
    wf = WORKFLOW_REGISTRY["flux_t2i_upscaled"]
    payload = wf.build_api_payload(dict(wf.default_params(), enhance=True))
    encode_id = _node_id(payload, "VAEEncode")
    sampler = next(n for n in payload.values()
                   if n["class_type"] == "KSampler"
                   and n["inputs"]["latent_image"] == [encode_id, 0])
    base = next(n for n in payload.values()
                if n["class_type"] == "KSampler" and n is not sampler)
    assert sampler["inputs"]["model"] == base["inputs"]["model"]
    assert sampler["inputs"]["positive"] == base["inputs"]["positive"]
    assert sampler["inputs"]["cfg"] == 1.0
    assert payload[encode_id]["inputs"]["vae"] == _find_node(payload, "VAEDecode")["inputs"]["vae"]


def test_flux_runs_its_lora_on_the_model_and_both_prompts_at_one_strength():
    wf = WORKFLOW_REGISTRY["flux_t2i_upscaled"]
    payload = wf.build_api_payload(dict(wf.default_params(), lora="example_style.safetensors",
                                        lora_strength=0.2, enhance=True))

    lora_id = _node_id(payload, "LoraLoader")
    lora = payload[lora_id]["inputs"]
    assert (lora["lora_name"], lora["strength_model"], lora["strength_clip"]) == (
        "example_style.safetensors", 0.2, 0.2)
    assert lora["model"] == [_node_id(payload, "UnetLoaderGGUF"), 0]
    assert lora["clip"] == [_node_id(payload, "DualCLIPLoader"), 0]
    assert {tuple(n["inputs"]["model"]) for n in payload.values()
            if n["class_type"] == "KSampler"} == {(lora_id, 0)}
    assert {tuple(n["inputs"]["clip"]) for n in payload.values()
            if n["class_type"] == "CLIPTextEncode"} == {(lora_id, 1)}
    assert graph_model_params(payload)["lora_strength"] == 0.2


def test_flux_with_no_lora_builds_the_graph_it_always_has():
    wf = WORKFLOW_REGISTRY["flux_t2i_upscaled"]
    payload = wf.build_api_payload(dict(wf.default_params(), lora=NO_LORA))

    assert _node_id(payload, "LoraLoader") is None
    assert _find_node(payload, "KSampler")["inputs"]["model"] == [
        _node_id(payload, "UnetLoaderGGUF"), 0]


def test_krea2_builds_the_turbo_graph_on_the_official_settings():
    wf = Krea2T2iWorkflow()
    params = dict(wf.default_params(), positive_prompt="a lighthouse at dusk", seed=7)
    payload = wf.build_api_payload(params)

    assert _find_node(payload, "UNETLoader")["inputs"] == {
        "unet_name": params["unet"], "weight_dtype": "default"}
    assert _find_node(payload, "CLIPLoader")["inputs"] == {
        "clip_name": params["clip_name"], "type": "krea2", "device": "default"}
    assert _find_node(payload, "VAELoader")["inputs"] == {"vae_name": params["vae"]}
    assert _find_node(payload, "CLIPTextEncode")["inputs"] == {
        "clip": [_node_id(payload, "CLIPLoader"), 0], "text": "a lighthouse at dusk"}
    assert _find_node(payload, "ConditioningZeroOut")["inputs"] == {
        "conditioning": [_node_id(payload, "CLIPTextEncode"), 0]}
    assert _find_node(payload, "EmptyLatentImage")["inputs"] == {
        "width": params["width"], "height": params["height"], "batch_size": 1}
    assert _find_node(payload, "KSampler")["inputs"] == {
        "model": [_node_id(payload, "UNETLoader"), 0],
        "positive": [_node_id(payload, "CLIPTextEncode"), 0],
        "negative": [_node_id(payload, "ConditioningZeroOut"), 0],
        "latent_image": [_node_id(payload, "EmptyLatentImage"), 0],
        "seed": 7, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
        "denoise": 1.0,
    }
    assert _find_node(payload, "VAEDecode")["inputs"] == {
        "samples": [_node_id(payload, "KSampler"), 0], "vae": [_node_id(payload, "VAELoader"), 0]}
    assert _find_node(payload, "SaveImage")["inputs"] == {
        "images": [_node_id(payload, "VAEDecode"), 0], "filename_prefix": "image/krea2_t2i"}


def test_krea2_offers_a_negative_prompt_and_prompt_strength_for_the_raw_model():
    wf = Krea2T2iWorkflow()
    pds = {pd.key: pd for pd in wf.param_definitions()}
    assert pds["negative_prompt"].type == "str"
    assert pds["negative_prompt"].default == ""
    assert pds["cfg"].label == "Prompt Strength"
    assert pds["cfg"].default == 1.0
    assert pds["steps"].max_val >= 52

    payload = wf.build_api_payload(dict(wf.default_params(), negative_prompt="blurry",
                                        cfg=3.5, steps=52))

    sampler = _find_node(payload, "KSampler")["inputs"]
    assert payload[sampler["negative"][0]] == {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": [_node_id(payload, "CLIPLoader"), 0], "text": "blurry"}}
    assert _find_node(payload, "ConditioningZeroOut") is None
    assert sampler["cfg"] == 3.5
    assert sampler["steps"] == 52


def test_krea2_runs_its_lora_on_the_model_alone():
    wf = Krea2T2iWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), lora="a_lora.safetensors",
                                        lora_strength=0.8))

    assert _find_node(payload, "LoraLoaderModelOnly")["inputs"] == {
        "model": [_node_id(payload, "UNETLoader"), 0],
        "lora_name": "a_lora.safetensors", "strength_model": 0.8}
    assert _find_node(payload, "KSampler")["inputs"]["model"] == [
        _node_id(payload, "LoraLoaderModelOnly"), 0]
    assert _find_node(payload, "CLIPTextEncode")["inputs"]["clip"] == [
        _node_id(payload, "CLIPLoader"), 0]

    bare = wf.build_api_payload(dict(wf.default_params(), lora=NO_LORA))
    assert _find_node(bare, "LoraLoaderModelOnly") is None
    assert _find_node(bare, "KSampler")["inputs"]["model"] == [_node_id(bare, "UNETLoader"), 0]


def test_krea2_offers_only_what_a_krea2_graph_can_run(installed_models):
    for family in ("krea2", "flux", "wan"):
        installed_models.add("diffusion_models", f"fam_{family}.safetensors", arch=family)
        installed_models.add("loras", f"fam_{family}.safetensors", arch=family, lora=True)
    installed_models.add("diffusion_models", "unreadable.safetensors")

    offered = {pd.key: pd.options for pd in Krea2T2iWorkflow().param_definitions()}

    assert offered["unet"] == ["fam_krea2.safetensors", "unreadable.safetensors"]
    assert offered["lora"] == [NO_LORA, "fam_krea2.safetensors"]


def test_krea2_loads_a_gguf_model_through_the_gguf_loader():
    # ComfyUI's own UNETLoader cannot read GGUF.
    wf = Krea2T2iWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), unet="krea2_turbo-Q6_K.gguf"))

    assert _find_node(payload, "UNETLoader") is None
    assert _find_node(payload, "UnetLoaderGGUF")["inputs"] == {"unet_name": "krea2_turbo-Q6_K.gguf"}
    assert _find_node(payload, "KSampler")["inputs"]["model"] == [
        _node_id(payload, "UnetLoaderGGUF"), 0]


def test_image_enhance_is_registered_and_derives_size_from_the_source(tmp_path, monkeypatch):
    wf = WORKFLOW_REGISTRY["image_enhance"]
    assert wf.__class__ is ImageEnhanceWorkflow
    assert wf.output_type == "image"
    assert wf.model_keys == ("checkpoint",)
    assert wf.default_params()["enhance_denoise"] == 0.15, (
        "at so low a denoise the SDXL checkpoint adds texture without repainting, "
        "which is what lets one enhancer serve whatever made the image")
    assert wf.seed_keys() == ("seed",)
    assert wf.selectable is False
    assert all(WORKFLOW_REGISTRY[n].selectable for n in WORKFLOW_REGISTRY
               if n != "image_enhance")
    assert wf.derives_size_from_input is True
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "src.png", (640, 360))
    params = dict(wf.default_params(), input_image="src.png", enhance_scale=2.0)
    assert wf.derived_display_size(params) == (1280, 720)
    assert wf.derived_display_size(dict(params, enhance_scale=1.5)) == (960, 540)
    assert wf.derived_display_size(dict(params, input_image="missing.png")) is None


def test_image_enhance_build_api_payload_structure():
    wf = WORKFLOW_REGISTRY["image_enhance"]
    params = dict(wf.default_params(), input_image="pick.png", seed=5,
                  positive_prompt="warm window light", enhance_scale=2.0,
                  enhance_steps=12, enhance_denoise=0.2)
    payload = wf.build_api_payload(params)

    load_id = _node_id(payload, "LoadImage")
    assert payload[load_id]["inputs"]["image"] == "pick.png"
    up_id = _node_id(payload, "ImageUpscaleWithModel")
    assert payload[up_id]["inputs"]["image"] == [load_id, 0]
    assert _find_node(payload, "ImageScaleBy")["inputs"]["scale_by"] == pytest.approx(0.5)
    encode_id = _node_id(payload, "VAEEncode")
    sampler = _find_node(payload, "KSampler")
    assert sampler["inputs"]["latent_image"] == [encode_id, 0]
    assert sampler["inputs"]["steps"] == 12
    assert sampler["inputs"]["denoise"] == 0.2
    assert sampler["inputs"]["seed"] == 5
    ckpt_id = _node_id(payload, "CheckpointLoaderSimple")
    assert sampler["inputs"]["model"] == [ckpt_id, 0]
    assert any(n["class_type"] == "CLIPTextEncode"
               and n["inputs"]["text"] == "warm window light"
               for n in payload.values())
    save_id = _node_id(payload, "SaveImage")
    assert wf.output_node_id == save_id
    final = payload[payload[save_id]["inputs"]["images"][0]]
    assert final["class_type"] == "VAEDecode"


def test_image_enhance_honors_an_unlocked_size_override():
    wf = WORKFLOW_REGISTRY["image_enhance"]
    params = dict(wf.default_params(), input_image="pick.png", width=1536, height=864)
    payload = wf.build_api_payload(params)
    assert _find_node(payload, "ImageScaleBy") is None
    scale = _find_node(payload, "ImageScale")
    up_id = _node_id(payload, "ImageUpscaleWithModel")
    assert scale["inputs"] == {
        "image": [up_id, 0], "upscale_method": "lanczos",
        "width": 1536, "height": 864, "crop": "disabled",
    }
    scale_id = _node_id(payload, "ImageScale")
    assert _find_node(payload, "VAEEncode")["inputs"]["pixels"] == [scale_id, 0]


_FOUND_DETECTORS = ("face_finder.pt", "hand_finder.pt", "teeth_finder.pt")


def _nodes_of(payload: dict, class_type: str) -> list[dict]:
    return [n for n in payload.values() if n.get("class_type") == class_type]


def _enhance_payload(installed=_FOUND_DETECTORS, outlined=(), **params):
    wf = WORKFLOW_REGISTRY["image_enhance"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(detail_module, "list_detector_files", lambda: list(installed))
        mp.setattr(detail_module, "list_outline_detector_files", lambda: list(outlined))
        return wf.build_api_payload(dict(wf.default_params(), input_image="pick.png",
                                         **params))


def test_a_mouth_fix_redraws_a_wider_area_than_the_lips_it_is_found_by():
    payload = _enhance_payload(installed=["hand_yolov8s.pt", "lips_v1.pt"],
                               enhance_detail_fixes={"hands": 0.4, "mouth": 0.4})

    detector_of = {node_id: node["inputs"]["model_name"] for node_id, node in payload.items()
                   if node.get("class_type") == "UltralyticsDetectorProvider"}
    grown = {detector_of[node["inputs"]["bbox_detector"][0]]: node["inputs"]["dilation"]
             for node in _nodes_of(payload, "BboxDetectorSEGS")}
    assert grown["bbox/lips_v1.pt"] > grown["bbox/hand_yolov8s.pt"]


def test_a_fix_given_a_lora_redraws_through_it_and_no_other_fix_does():
    payload = _enhance_payload(
        installed=["hand_yolov8s.pt", "face_yolov8m.pt"],
        enhance_detail_fixes={"faces": 0.3, "hands": 0.4},
        enhance_fix_prompts={"hands": {"lora": "my_hands.safetensors", "strength": 0.7}})

    ((lora_id, lora),) = [(node_id, node) for node_id, node in payload.items()
                          if node.get("class_type") == "LoraLoader"]
    assert lora["inputs"]["lora_name"] == "my_hands.safetensors"
    assert lora["inputs"]["strength_model"] == lora["inputs"]["strength_clip"] == 0.7
    fixes = {node["_meta"]["title"]: node for node in _nodes_of(payload, "DetailerForEach")}
    hands, faces = fixes["Hands fix"]["inputs"], fixes["Faces fix"]["inputs"]
    assert (hands["model"], hands["clip"]) == ([lora_id, 0], [lora_id, 1])
    assert payload[hands["positive"][0]]["inputs"]["clip"] == [lora_id, 1]
    assert lora_id not in (faces["model"][0], faces["clip"][0])


def test_every_part_is_at_zero_by_default_and_adds_nothing():
    wf = WORKFLOW_REGISTRY["image_enhance"]
    assert wf.default_params()["enhance_detail_fixes"] == {}, (
        "the detail pass is a second opinion on a few small regions: each part needs its "
        "detector installed and costs a sampling run for every region found")
    payload = wf.build_api_payload(dict(wf.default_params(), input_image="pick.png"))
    assert _nodes_of(payload, "UltralyticsDetectorProvider") == []
    assert _nodes_of(payload, "DetailerForEach") == []


def test_each_part_asked_for_is_re_sampled_in_place_at_its_own_denoise():
    payload = _enhance_payload(
        seed=5, enhance_detail_fixes={"faces": 0.45, "hands": 0.6},
    )

    providers = {nid: n for nid, n in payload.items()
                 if n["class_type"] == "UltralyticsDetectorProvider"}
    assert sorted(n["inputs"]["model_name"] for n in providers.values()) == [
        "bbox/face_finder.pt", "bbox/hand_finder.pt",
    ]

    detailers = {nid: n for nid, n in payload.items()
                 if n["class_type"] == "DetailerForEach"}
    assert len(detailers) == 2
    denoises = {}
    for node in detailers.values():
        segs = payload[node["inputs"]["segs"][0]]
        assert segs["class_type"] == "BboxDetectorSEGS"
        assert segs["inputs"]["bbox_detector"][0] in providers
        assert segs["inputs"]["image"] == node["inputs"]["image"], (
            "each detector reads the very image its detailer repaints, "
            "so what it found lands where it found it")
        assert node["inputs"]["seed"] == 5
        model = payload[segs["inputs"]["bbox_detector"][0]]["inputs"]["model_name"]
        denoises[model] = node["inputs"]["denoise"]
    assert denoises == {"bbox/face_finder.pt": 0.45, "bbox/hand_finder.pt": 0.6}, (
        "the whole-image pass is too gentle to mend a part, and a denoise that would redraw "
        "a hand would redraw everything else too, so each part gets a pass at its own")

    decode_id = _node_id(payload, "VAEDecode")
    first = next(nid for nid, n in detailers.items()
                 if n["inputs"]["image"] == [decode_id, 0])
    second = next(nid for nid in detailers if nid != first)
    assert detailers[second]["inputs"]["image"] == [first, 0]
    assert payload[_node_id(payload, "SaveImage")]["inputs"]["images"] == [second, 0], (
        "saved off the tail's decode, every pass would run and be thrown away")


def _linked(payload: dict, ref) -> dict:
    return payload[ref[0]]


def test_each_pass_reports_the_regions_its_detector_found_then_the_whole_image():
    payload = _enhance_payload(enhance_detail_fixes={"faces": 0.45, "hands": 0.6})

    reports = _nodes_of(payload, "PreviewAny")

    assert len(reports) == 2
    joined = []
    for report in reports:
        assert report["inputs"]["source"][1] == 3
        each = _linked(payload, _linked(payload, report["inputs"]["source"])["inputs"]["seg_elt"])
        joined.append(_linked(payload, each["inputs"]["segs"]))
    assert {tuple(concat["inputs"]["segs1"]) for concat in joined} == {
        tuple(detailer["inputs"]["segs"]) for detailer in _nodes_of(payload, "DetailerForEach")}
    assert {_linked(payload, concat["inputs"]["segs2"])["class_type"] for concat in joined} == {"MaskToSEGS"}
    assert _find_node(payload, "GetImageSize")["inputs"]["image"] == [_node_id(payload, "VAEDecode"), 0]


def _region(*edges) -> str:
    return json.dumps(list(edges), indent=4)


WHOLE_IMAGE = _region(0, 0, 2000, 1000)
FACE_PLACE = {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.5}
HAND_PLACE = {"left": 0.6, "top": 0.5, "right": 0.9, "bottom": 0.9}
ENHANCED = {"filename": "image_enhance_00007_.png", "subfolder": "image", "type": "output"}


def test_the_places_the_fixes_found_ride_with_the_image_they_were_found_in_in_the_order_they_ran():
    history = {"outputs": {
        "12": {"images": [ENHANCED]},
        "fix1_points": {"text": [_region(1200, 500, 1800, 900), WHOLE_IMAGE]},
        "fix0_points": {"text": [_region(200, 100, 600, 500), WHOLE_IMAGE]},
    }}

    files = WORKFLOW_REGISTRY["image_enhance"].extract_output_info(history)

    assert files == [{**ENHANCED, **points_of_interest.kept([FACE_PLACE, HAND_PLACE])}]


def test_the_places_say_which_part_found_them_and_each_eye_is_kept_as_it_was_found():
    history = {
        "prompt": [3, "run", {"fix0_detector": {"class_type": "UltralyticsDetectorProvider",
                                                 "inputs": {"model_name": "bbox/eye_finder.pt"}}}, {}, []],
        "outputs": {
            "12": {"images": [ENHANCED]},
            "fix0_points": {"text": [_region(200, 100, 600, 500), _region(500, 120, 900, 520), WHOLE_IMAGE]},
        },
    }

    files = WORKFLOW_REGISTRY["image_enhance"].extract_output_info(history)

    assert files[0]["points_of_interest"] == [
        {"left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.5, "part": "eyes"},
        {"left": 0.25, "top": 0.12, "right": 0.45, "bottom": 0.52, "part": "eyes"}]


def test_an_enhancement_whose_fixes_found_nothing_says_it_looked_and_found_no_places():
    history = {"outputs": {"12": {"images": [ENHANCED]}, "fix0_points": {"text": [WHOLE_IMAGE]}}}

    assert WORKFLOW_REGISTRY["image_enhance"].extract_output_info(history) == [
        {**ENHANCED, **points_of_interest.kept([])}]


def test_an_enhancement_that_fixed_no_part_carries_no_places_at_all():
    history = {"outputs": {"12": {"images": [ENHANCED]}}}

    assert WORKFLOW_REGISTRY["image_enhance"].extract_output_info(history) == [ENHANCED]


def test_a_region_reported_in_a_shape_no_fix_writes_is_passed_over():
    history = {"outputs": {"12": {"images": [ENHANCED]}, "fix0_points": {
        "text": ["a corner", _region(200, 100, 600, 500), _region(1, 2), WHOLE_IMAGE]}}}

    files = WORKFLOW_REGISTRY["image_enhance"].extract_output_info(history)

    assert files[0]["points_of_interest"] == [FACE_PLACE]


def test_a_third_part_is_a_third_pass_on_the_chain():
    payload = _enhance_payload(
        enhance_detail_fixes={"faces": 0.4, "hands": 0.5, "teeth": 0.6})
    assert len(_nodes_of(payload, "DetailerForEach")) == 3, (
        "the parts are found by different detectors and redrawn on their own settings, "
        "so each is a pass over the last one's output rather than one merged list of regions")
    assert len(_nodes_of(payload, "UltralyticsDetectorProvider")) == 3


def test_the_detail_pass_borrows_the_enhances_model_settings_and_vae():
    payload = _enhance_payload(
        positive_prompt="a lantern on a jetty",
        enhance_detail_fixes={"faces": 0.45, "hands": 0.45},
    )
    sampler = _find_node(payload, "KSampler")["inputs"]
    detailer = _nodes_of(payload, "DetailerForEach")[0]["inputs"]
    ckpt_id = _node_id(payload, "CheckpointLoaderSimple")
    assert detailer["model"] == sampler["model"] == [ckpt_id, 0], (
        "redrawn on the enhance's own model, settings and prompts, a part stays in the "
        "image's style rather than the sampler's idea of that part")
    assert detailer["clip"] == [ckpt_id, 1]
    assert detailer["vae"] == _find_node(payload, "VAEEncode")["inputs"]["vae"]
    assert detailer["steps"] == sampler["steps"]
    assert detailer["cfg"] == sampler["cfg"]
    assert detailer["sampler_name"] == sampler["sampler_name"]
    assert detailer["scheduler"] == sampler["scheduler"]


def test_a_detector_comfyui_hasnt_got_drops_its_part_rather_than_failing_the_submit():
    payload = _enhance_payload(
        installed=["face_finder.pt"],
        enhance_detail_fixes={"faces": 0.45, "hands": 0.45},
    )
    (provider,) = _nodes_of(payload, "UltralyticsDetectorProvider")
    assert provider["inputs"]["model_name"] == "bbox/face_finder.pt"
    (detailer,) = _nodes_of(payload, "DetailerForEach")
    assert detailer["inputs"]["image"] == [_node_id(payload, "VAEDecode"), 0]
    save = payload[_node_id(payload, "SaveImage")]
    assert save["inputs"]["images"] == [_node_id(payload, "DetailerForEach"), 0]


def test_asking_for_parts_with_nothing_installed_builds_none_of_it():
    payload = _enhance_payload(installed=[],
                               enhance_detail_fixes={"faces": 0.45})
    assert _nodes_of(payload, "DetailerForEach") == []
    save = payload[_node_id(payload, "SaveImage")]
    assert save["inputs"]["images"] == [_node_id(payload, "VAEDecode"), 0]


def test_the_detail_passs_setting_is_defined_with_the_range_its_spinners_take():
    defs = {pd.key: pd
            for pd in WORKFLOW_REGISTRY["image_enhance"].param_definitions()}

    assert defs["enhance_detail_fixes"].default == {}
    assert defs["enhance_detail_fixes"].min_val > 0
    assert defs["enhance_detail_fixes"].max_val == 1.0


def test_sdxl_workflows_end_with_an_upscale_enhance_pass():
    for name in ("sdxl_t2i", "sdxl_pose_transfer"):
        wf = WORKFLOW_REGISTRY[name]
        params = dict(wf.default_params(), seed=11, enhance=True, enhance_scale=2.0,
                      enhance_steps=17, enhance_denoise=0.35)
        payload = wf.build_api_payload(params)

        loader_id = _node_id(payload, "UpscaleModelLoader")
        assert payload[loader_id]["inputs"]["model_name"] == params["upscale_model"], name
        up_id = _node_id(payload, "ImageUpscaleWithModel")
        assert payload[up_id]["inputs"]["upscale_model"] == [loader_id, 0]
        scale_id = _node_id(payload, "ImageScaleBy")
        assert scale_id is not None, (
            f"{name}: its width and height fields are the base render's, and an enhance "
            "rescaled to them would come out the base render's size")
        scale = payload[scale_id]["inputs"]
        assert scale["image"] == [up_id, 0]
        assert scale["scale_by"] == pytest.approx(2.0 / 4.0)
        encode_id = _node_id(payload, "VAEEncode")
        assert payload[encode_id]["inputs"]["pixels"] == [scale_id, 0]

        samplers = {nid: n["inputs"] for nid, n in payload.items()
                    if n["class_type"] == "KSampler"}
        assert len(samplers) == 2, name
        enhance_id = next(nid for nid, s in samplers.items()
                          if s["latent_image"] == [encode_id, 0])
        base_id = next(nid for nid in samplers if nid != enhance_id)
        base, enhance = samplers[base_id], samplers[enhance_id]
        assert enhance["steps"] == 17
        assert enhance["denoise"] == 0.35
        assert enhance["seed"] == 11
        assert enhance["model"] == base["model"]
        assert enhance["positive"] == base["positive"]
        assert enhance["negative"] == base["negative"]
        assert enhance["cfg"] == base["cfg"]
        assert enhance["sampler_name"] == base["sampler_name"]
        assert enhance["scheduler"] == base["scheduler"]

        base_decode_id = payload[up_id]["inputs"]["image"][0]
        assert payload[base_decode_id]["class_type"] == "VAEDecode"
        assert payload[base_decode_id]["inputs"]["samples"] == [base_id, 0]
        save = _find_node(payload, "SaveImage")
        final_decode_id = save["inputs"]["images"][0]
        assert payload[final_decode_id]["class_type"] == "VAEDecode"
        assert payload[final_decode_id]["inputs"]["samples"] == [enhance_id, 0]
        assert payload[final_decode_id]["inputs"]["vae"] == payload[encode_id]["inputs"]["vae"]
        assert wf.extract_output_info(
            {"outputs": {_node_id(payload, "SaveImage"): {"images": [{"filename": "x.png"}]}}}
        ) == [{"filename": "x.png"}]


def test_sdxl_workflows_expose_the_enhance_settings(monkeypatch):
    installed = {"upscale_models": ["4x_crisp.pt", "4x_soft.pth"]}
    def dropdown(category, fallback, **terms):
        return installed.get(category, list(fallback))
    monkeypatch.setattr(dropdowns, "list_model_files", dropdown)

    for name in ("sdxl_t2i", "sdxl_pose_transfer"):
        wf = WORKFLOW_REGISTRY[name]
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        model = by_key["upscale_model"]
        assert model.type == "dropdown"
        assert model.options == ["4x_crisp.pt", "4x_soft.pth"]
        assert model.default == wf.default_params()["upscale_model"]
        scale = by_key["enhance_scale"]
        assert scale.type == "float"
        assert (scale.min_val, scale.max_val) == (1.0, 4.0)
        assert scale.default == 2.0
        assert by_key["enhance_steps"].type == "int"
        denoise = by_key["enhance_denoise"]
        assert denoise.type == "float"
        assert denoise.max_val == 1.0
        assert denoise.default == 0.15


_FAMILIES = ("sdxl", "sd15", "flux", "qwen", "wan", "wan_t2v", "wan_fun_control",
             "wan_animate", "ltx", "krea2")
_MIXED_CATEGORIES = ("checkpoints", "diffusion_models", "controlnet", "loras")
_SUITS_EVERY_FAMILY = "upscale_models"


def test_no_picker_offers_a_model_its_graph_cannot_run(installed_models):
    for category in _MIXED_CATEGORIES:
        for family in _FAMILIES:
            installed_models.add(
                category, f"fam_{family}.safetensors",
                arch=family, lora=(category == "loras"),
            )
    installed_models.add_bytes(_SUITS_EVERY_FAMILY, "an_upscaler.pt", b"not a safetensors")

    planted = {f"fam_{family}.safetensors" for family in _FAMILIES}
    checked = 0
    for name, wf in WORKFLOW_REGISTRY.items():
        for pd in wf.param_definitions():
            if pd.type != "dropdown" or not pd.options:
                continue
            offered = planted.intersection(pd.options)
            if not offered:
                continue
            checked += 1
            assert offered < planted, f"{name}.{pd.key} offers every architecture"
    assert checked, "no model dropdowns were exercised — the fixture stopped matching"


def test_an_image_to_video_form_offers_no_model_that_makes_video_from_text_or_a_control_video(
        installed_models):
    families = ("wan", "wan_t2v", "wan_fun_control")
    for family in families:
        installed_models.add("diffusion_models", f"fam_{family}.safetensors", arch=family)
    kinds = {f"fam_{family}.safetensors" for family in families}

    for workflow in ("wan22_i2v", "wan22_flf2v_loop"):
        for pd in WORKFLOW_REGISTRY[workflow].param_definitions():
            if pd.key in ("unet_high", "unet_low"):
                assert kinds.intersection(pd.options) == {"fam_wan.safetensors"}, (
                    f"{workflow}.{pd.key}")


def test_an_image_to_video_form_offers_no_lora_civitai_files_under_text_to_video(
        installed_models, recorded_base_models):
    for stem in ("a_t2v_look", "an_i2v_look", "a_look_not_on_civitai"):
        installed_models.add("loras", f"{stem}.safetensors", arch="wan", lora=True)
    recorded_base_models({"a_t2v_look": "Wan Video 2.2 T2V-A14B",
                          "an_i2v_look": "Wan Video 2.2 I2V-A14B"})
    looks = {"a_t2v_look.safetensors", "an_i2v_look.safetensors",
             "a_look_not_on_civitai.safetensors"}

    for workflow in ("wan22_i2v", "wan22_flf2v_loop", "wan22_animate"):
        lora_keys = WORKFLOW_REGISTRY[workflow].lora_keys
        dropdowns = [pd for pd in WORKFLOW_REGISTRY[workflow].param_definitions()
                   if pd.key in lora_keys]
        assert dropdowns, workflow
        for pd in dropdowns:
            assert looks.intersection(pd.options) == looks - {"a_t2v_look.safetensors"}, (
                f"{workflow}.{pd.key}")


def test_a_form_that_decodes_with_the_sdxl_vae_offers_no_sd15_checkpoint(installed_models):
    installed_models.add("checkpoints", "an_xl_model.safetensors", arch="sdxl")
    installed_models.add("checkpoints", "a_15_model.safetensors", arch="sd15")

    for workflow in ("sdxl_t2i", "sdxl_pose_transfer", "image_enhance"):
        checkpoint = next(pd for pd in WORKFLOW_REGISTRY[workflow].param_definitions()
                          if pd.key == "checkpoint")
        assert {"an_xl_model.safetensors", "a_15_model.safetensors"}.intersection(
            checkpoint.options) == {"an_xl_model.safetensors"}, workflow


def test_every_wan_expert_slot_rejects_the_other_half(installed_models):
    for category in ("diffusion_models", "loras"):
        for half in ("high", "low"):
            installed_models.add(
                category, f"wan_{half}_noise.safetensors",
                arch="wan", lora=(category == "loras"),
            )

    checked = 0
    for name, wf in WORKFLOW_REGISTRY.items():
        for pd in wf.param_definitions():
            if pd.type != "dropdown" or not pd.options:
                continue
            for half, other in (("high", "low"), ("low", "high")):
                if not pd.key.endswith(f"_{half}"):
                    continue
                assert f"wan_{half}_noise.safetensors" in pd.options, f"{name}.{pd.key}"
                assert f"wan_{other}_noise.safetensors" not in pd.options, f"{name}.{pd.key}"
                checked += 1
    assert checked, "no high/low slots were exercised"


def test_each_workflow_a_person_picks_is_offered_for_the_kind_it_makes_and_no_other():
    for name, wf in WORKFLOW_REGISTRY.items():
        offered_for = {kind for kind in MediaType if wf in offered_workflows(makes=kind)}
        assert offered_for == ({wf.output_type} if wf.selectable else set()), name


def test_a_tab_that_makes_nothing_yet_is_offered_the_workflows_of_both_kinds():
    assert set(offered_workflows(makes=None)) == {
        *offered_workflows(makes=MediaType.IMAGE), *offered_workflows(makes=MediaType.VIDEO)}


def test_every_workflow_name_says_t2i_i2v_and_t2v_rather_than_spelling_them_out():
    names = [wf.display_name for wf in WORKFLOW_REGISTRY.values()]
    names += [workflow_named(outside_workflow("a-site", MediaType.VIDEO, kind)).display_name
              for kind in VideoKind]
    spelled_out = re.compile(r"text-to-image|image-to-video|text-to-video", re.IGNORECASE)
    assert [name for name in [*names, *RETIRED_WORKFLOW_NAMES.values()]
            if spelled_out.search(name)] == []


def test_enhance_keys_cover_every_param_only_the_tail_reads():
    for name in ("sdxl_t2i", "sdxl_pose_transfer", "wan22_t2i", "krea2_t2i"):
        wf = WORKFLOW_REGISTRY[name]
        assert set(wf.enhance_keys()) == {
            "enhance", "upscale_model", "enhance_scale", "enhance_steps", "enhance_denoise",
        }, name
    assert set(WORKFLOW_REGISTRY["flux_t2i_upscaled"].enhance_keys()) == {
        "enhance", "enhance_scale", "enhance_steps", "enhance_denoise",
    }
    assert WORKFLOW_REGISTRY["wan22_i2v"].enhance_keys() == ()


def _every_link(payload: dict):
    for reader, node in payload.items():
        for name, value in node.get("inputs", {}).items():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and isinstance(value[1], int)):
                yield reader, name, value[0]


@pytest.mark.parametrize("enhance", [False, True])
def test_no_workflow_can_build_a_graph_with_a_link_to_a_node_it_lost(enhance, monkeypatch):
    monkeypatch.setattr(detail_module, "list_detector_files",
                        lambda: list(_FOUND_DETECTORS))

    checked = 0
    for name, wf in WORKFLOW_REGISTRY.items():
        params = dict(wf.default_params(), input_image="start.png", seed=3)
        if "enhance" in params:
            params["enhance"] = enhance
        if "enhance_detail_fixes" in params:
            params["enhance_detail_fixes"] = {"faces": 0.4, "hands": 0.5}
        payload = wf.build_api_payload(params)

        for reader, field, target in _every_link(payload):
            assert target in payload, f"{name}: node {reader}.{field} -> missing {target}"
        checked += 1
    assert checked == len(WORKFLOW_REGISTRY)


def test_a_shared_fragment_never_builds_under_an_id_a_hand_numbered_graph_could_pick():
    fragment_ids = {
        base._SIZE_SCALE, base._SIZE_GET,
        base._ENH_LOADER, base._ENH_UPSCALE, base._ENH_RESCALE,
        base._ENH_ENCODE, base._ENH_SAMPLER, base._ENH_DECODE,
    }
    assert not any(node_id.isdigit() for node_id in fragment_ids)

    payload = _enhance_payload(enhance_detail_fixes={"faces": 0.4, "hands": 0.5})
    detail_ids = [nid for nid, node in payload.items()
                  if node["class_type"] in
                  ("UltralyticsDetectorProvider", "BboxDetectorSEGS", "DetailerForEach")]
    assert len(detail_ids) == 6
    assert not any(node_id.isdigit() for node_id in detail_ids)


def test_a_form_starts_on_the_value_stored_settings_are_normalized_against():
    checked = 0
    for name, wf in WORKFLOW_REGISTRY.items():
        defaults = wf.default_params()
        for pd in wf.param_definitions():
            assert pd.key in defaults, f"{name}.{pd.key} is on the form but has no default"
            assert pd.default == defaults[pd.key], (
                f"{name}.{pd.key}: a fresh item would land in a different folder "
                "from an identical re-roll, with nothing to say so")
            checked += 1
    assert checked > 100, "the registry stopped being walked"


def test_wan22_default_params_has_required_keys():
    wf = Wan22Flf2vLoopWorkflow()
    params = wf.default_params()
    required = {
        "positive_prompt", "negative_prompt", "input_image",
        "noise_seed", "seed",
        "frame_count", "frame_rate",
        "lora_strength_high", "lora_strength_low",
    }
    assert required.issubset(params.keys())
    assert "width" not in params
    assert "height" not in params


def test_i2v_workflows_have_no_manual_width_height_controls():
    i2v_workflows = [
        wf for wf in WORKFLOW_REGISTRY.values() if "input_image" in wf.default_params()
    ]
    assert len(i2v_workflows) >= 2
    for wf in i2v_workflows:
        keys = [d.key for d in wf.param_definitions()]
        assert "width" not in keys, wf.name
        assert "height" not in keys, wf.name
        params = wf.default_params()
        assert "width" not in params, wf.name
        assert "height" not in params, wf.name


def test_every_input_image_workflow_derives_its_size():
    for wf in WORKFLOW_REGISTRY.values():
        takes_image = "input_image" in wf.default_params()
        assert wf.derives_size_from_input == takes_image, wf.name


def test_derived_display_size_measures_the_input_image(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "wide.png", (1920, 1080))

    for name in ("wan22_i2v", "wan22_flf2v_loop"):
        wf = WORKFLOW_REGISTRY[name]
        params = dict(wf.default_params(), input_image="wide.png")
        assert wf.derived_display_size(params) == scale_to_total_pixels(1920, 1080), name


def test_derived_display_size_is_none_when_not_derived_or_unmeasurable():
    manual = WORKFLOW_REGISTRY["sdxl_t2i"]
    assert manual.derives_size_from_input is False
    assert manual.derived_display_size(manual.default_params()) is None

    i2v = WORKFLOW_REGISTRY["wan22_i2v"]
    assert i2v.derived_display_size(dict(i2v.default_params(), input_image="")) is None, (
        "the form shows no size until the image can be measured, rather than a guess")
    assert i2v.derived_display_size(
        dict(i2v.default_params(), input_image="does_not_exist.png")
    ) is None


def test_wan22_build_api_payload_structure():
    wf = Wan22Flf2vLoopWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "video prompt"
    params["negative_prompt"] = ""
    params["noise_seed"] = 42
    params["seed"] = 99
    params["input_image"] = "test.png"
    payload = wf.build_api_payload(params)
    assert payload["9"]["class_type"] == "CLIPTextEncode"
    assert payload["9"]["inputs"]["text"] == "video prompt"
    assert payload["11"]["class_type"] == "LoadImage"
    assert payload["11"]["inputs"]["image"] == "test.png"
    assert payload["13"]["class_type"] == "KSamplerAdvanced"
    assert payload["13"]["inputs"]["noise_seed"] == 42
    assert payload["14"]["inputs"]["noise_seed"] == 99
    assert payload["16"]["class_type"] == "VHS_VideoCombine"
    scale_id = _node_id(payload, "ImageScaleToTotalPixels")
    getsize_id = _node_id(payload, "GetImageSize")
    assert payload[scale_id]["inputs"]["image"] == ["11", 0]
    assert payload[scale_id]["inputs"]["resolution_steps"] == 16
    assert payload[getsize_id]["inputs"]["image"] == [scale_id, 0]
    assert payload["12"]["inputs"]["width"] == [getsize_id, 0]
    assert payload["12"]["inputs"]["height"] == [getsize_id, 1]
    assert payload["12"]["inputs"]["length"] == params["frame_count"]


def test_wan22_i2v_size_override_replaces_the_in_graph_derivation():
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    params = dict(wf.default_params(), input_image="x.png", width=1024, height=576)
    payload = wf.build_api_payload(params)

    assert _find_node(payload, "ImageScaleToTotalPixels") is None
    assert _find_node(payload, "GetImageSize") is None
    scale_id = _node_id(payload, "ImageScale")
    assert payload[scale_id]["inputs"] == {
        "image": ["12", 0], "upscale_method": "lanczos",
        "width": 1024, "height": 576, "crop": "disabled",
    }
    video = payload["14"]["inputs"]
    assert video["start_image"] == [scale_id, 0]
    assert video["width"] == 1024
    assert video["height"] == 576


def test_wan22_flf2v_size_override_replaces_the_in_graph_derivation():
    wf = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    params = dict(wf.default_params(), input_image="x.png", width=848, height=480)
    payload = wf.build_api_payload(params)

    assert _find_node(payload, "ImageScaleToTotalPixels") is None
    scale_id = _node_id(payload, "ImageScale")
    frame = payload["12"]["inputs"]
    assert frame["start_image"] == [scale_id, 0]
    assert frame["end_image"] == [scale_id, 0]
    assert frame["width"] == 848
    assert frame["height"] == 480


def test_wan22_flf2v_payload_generates_synced_foley_audio():
    wf = Wan22Flf2vLoopWorkflow()
    params = dict(wf.default_params(), audio_prompt="wet rhythmic slapping", audio_seed=3)
    payload = wf.build_api_payload(params)

    sampler_id = _node_id(payload, "HunyuanFoleySampler")
    sampler = payload[sampler_id]["inputs"]
    decode_id = _node_id(payload, "VAEDecode")
    assert sampler["image"] == [decode_id, 0]
    assert sampler["frame_rate"] == params["frame_rate"]
    assert sampler["prompt"] == "wet rhythmic slapping"
    assert sampler["seed"] == 3
    assert _find_node(payload, "HunyuanModelLoader") is not None
    assert _find_node(payload, "HunyuanDependenciesLoader") is not None

    combine = _find_node(payload, "VHS_VideoCombine")
    assert combine["inputs"]["audio"] == [sampler_id, 0]


def test_foley_duration_never_undercuts_the_models_one_second_floor():
    # ComfyUI's HunyuanFoley rejects durations under one second.
    wf = Wan22Flf2vLoopWorkflow()
    params = dict(wf.default_params(), frame_count=5, frame_rate=16.0)
    payload = wf.build_api_payload(params)
    assert _find_node(payload, "HunyuanFoleySampler")["inputs"]["duration"] == 1.0

    params = dict(wf.default_params(), frame_count=21, frame_rate=16.0)
    payload = wf.build_api_payload(params)
    sampler = _find_node(payload, "HunyuanFoleySampler")
    assert sampler["inputs"]["duration"] == pytest.approx(21 / 16.0)


def test_wan22_extract_output_info():
    wf = Wan22Flf2vLoopWorkflow()
    history = {
        "outputs": {
            "16": {
                "gifs": [
                    {"filename": "flf2v_loop_00001.mp4", "subfolder": "video", "type": "output"}
                ]
            }
        }
    }
    files = wf.extract_output_info(history)
    assert len(files) == 1
    assert files[0]["filename"] == "flf2v_loop_00001.mp4"


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_a_videos_file_with_sound_is_listed_beside_its_soundless_copy(name):
    wf = WORKFLOW_REGISTRY[name]
    stem = wf.default_params()["filename_prefix"].rpartition("/")[2] + "_00001"
    history = {"outputs": {wf.output_node_id: {"gifs": [
        {"filename": f"{stem}-audio.mp4", "subfolder": "video", "type": "output",
         "workflow": f"{stem}.png"},
    ]}}}
    files = wf.extract_output_info(history)
    assert [f["filename"] for f in files] == [f"{stem}-audio.mp4", f"{stem}.mp4"]
    assert files[1] == {"filename": f"{stem}.mp4", "subfolder": "video",
                        "type": "output", "role": "silent"}


def test_wan22_i2v_default_params_has_required_keys():
    wf = Wan22I2vWorkflow()
    params = wf.default_params()
    required = {
        "positive_prompt", "negative_prompt", "input_image",
        "noise_seed", "seed",
        "frame_count", "frame_rate",
        "steps", "cfg_high", "cfg_low", "shift_high", "shift_low",
        "lora_strength_high", "lora_strength_low",
    }
    assert required.issubset(params.keys())
    assert "width" not in params
    assert "height" not in params


def test_every_wan22_i2v_setting_is_declared_as_a_paramdef():
    wf = Wan22I2vWorkflow()
    defs = wf.param_definitions()
    assert len(defs) > 0
    assert all(isinstance(d, ParamDef) for d in defs)
    keys = [d.key for d in defs]
    assert "input_image" in keys
    assert "positive_prompt" in keys


def test_wan22_i2v_build_api_payload_structure():
    wf = Wan22I2vWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "video prompt"
    params["negative_prompt"] = "bad"
    params["input_image"] = "start.png"
    params["noise_seed"] = 842719365028413
    params["seed"] = 0
    payload = wf.build_api_payload(params)

    i2v = _find_node(payload, "WanImageToVideo")
    assert i2v is not None
    assert i2v["inputs"]["length"] == params["frame_count"]
    assert _find_node(payload, "WanFirstLastFrameToVideo") is None

    load_id = _node_id(payload, "LoadImage")
    scale_id = _node_id(payload, "ImageScaleToTotalPixels")
    getsize_id = _node_id(payload, "GetImageSize")
    assert payload[scale_id]["inputs"]["image"] == [load_id, 0]
    assert payload[scale_id]["inputs"]["resolution_steps"] == 16
    assert payload[getsize_id]["inputs"]["image"] == [scale_id, 0]
    assert i2v["inputs"]["width"] == [getsize_id, 0]
    assert i2v["inputs"]["height"] == [getsize_id, 1]
    assert i2v["inputs"]["start_image"] == [scale_id, 0]
    assert "width" not in params
    assert "height" not in params

    assert payload[load_id]["inputs"]["image"] == "start.png"

    assert _find_node(payload, "CLIPVisionEncode") is not None

    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    assert len(samplers) == 2
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["noise_seed"] == 842719365028413
    assert high["inputs"]["end_at_step"] == params["steps"] // 2
    assert low["inputs"]["start_at_step"] == params["steps"] // 2

    assert any(
        n["class_type"] == "CLIPTextEncode" and n["inputs"]["text"] == "video prompt"
        for n in payload.values()
    )


def test_wan22_i2v_zero_split_still_hands_off_at_half_the_steps():
    wf = Wan22I2vWorkflow()
    params = dict(wf.default_params(), steps=20)
    payload = wf.build_api_payload(params)

    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["end_at_step"] == 10
    assert low["inputs"]["start_at_step"] == 10


def test_settings_stored_with_one_shared_strength_still_render_at_that_strength():
    wf = Wan22I2vWorkflow()
    stored = dict(wf.default_params(), steps=20, cfg=1.0, cfg_high=0.0, cfg_low=0.0)
    payload = wf.build_api_payload(stored)

    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    assert [n["inputs"]["cfg"] for n in samplers] == [1.0, 1.0]

    tuned = dict(stored, cfg_high=2.0)
    tuned_payload = wf.build_api_payload(tuned)
    high = next(n for n in tuned_payload.values()
                if n["class_type"] == "KSamplerAdvanced"
                and n["inputs"]["add_noise"] == "enable")
    assert high["inputs"]["cfg"] == 2.0


def test_wan22_i2v_payload_generates_synced_foley_audio():
    wf = Wan22I2vWorkflow()
    params = dict(
        wf.default_params(),
        audio_prompt="rhythmic audio",
        audio_negative_prompt="music",
        audio_seed=7,
        foley_model="another_foley_model.safetensors",
    )
    payload = wf.build_api_payload(params)

    sampler_id = _node_id(payload, "HunyuanFoleySampler")
    sampler = payload[sampler_id]["inputs"]
    decode_id = _node_id(payload, "VAEDecode")
    assert sampler["image"] == [decode_id, 0]
    assert sampler["frame_rate"] == params["frame_rate"]
    assert sampler["duration"] == pytest.approx(params["frame_count"] / params["frame_rate"])
    assert sampler["prompt"] == "rhythmic audio"
    assert sampler["negative_prompt"] == "music"
    assert sampler["seed"] == 7

    model_id = _node_id(payload, "HunyuanModelLoader")
    deps_id = _node_id(payload, "HunyuanDependenciesLoader")
    assert sampler["hunyuan_model"] == [model_id, 0]
    assert sampler["hunyuan_deps"] == [deps_id, 0]
    assert payload[model_id]["inputs"]["model_name"] == params["foley_model"], (
        "named in the settings, so a video records which sound model scored it")
    assert payload[deps_id]["inputs"]["vae_name"] == params["foley_vae"]
    assert payload[deps_id]["inputs"]["synchformer_name"] == params["foley_synchformer"]

    assert payload[wf.output_node_id]["inputs"]["audio"] == [sampler_id, 0]


@pytest.mark.parametrize("listed_under", ["images", "gifs"])
def test_a_runs_file_is_found_whichever_key_its_save_node_listed_it_under(listed_under):
    wf = Wan22I2vWorkflow()
    saved = {"filename": "wan22_i2v_00001_.mp4", "subfolder": "video", "type": "output"}
    history = {"outputs": {wf.output_node_id: {listed_under: [saved], "animated": [True]}}}

    assert wf.extract_output_info(history) == [saved]


def _write_image(path, size):
    Image.new("RGB", size, (128, 128, 128)).save(path)


def test_sdxl_pose_transfer_is_registered_as_an_image_workflow():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    assert wf.__class__ is SdxlPoseTransferWorkflow
    assert wf.name == "sdxl_pose_transfer"
    assert wf.output_type == "image"
    assert wf.model_keys == ("checkpoint",)
    assert wf.seed_keys() == ("seed",)
    assert wf.derives_size_from_input is True


def test_sdxl_pose_transfer_structure_image_browses_the_custom_poses_folder():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    pd = next(pd for pd in wf.param_definitions() if pd.key == "input_image")
    assert pd.browse_dir == config.CUSTOM_POSES_DIR
    assert config.CUSTOM_POSES_DIR == config.LIBRARY_ROOT / "images" / "custom_poses"


def _enhanced_sdxl_pose_transfer_payload() -> tuple[dict, dict]:
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(
        wf.default_params(),
        positive_prompt="a figure in a sunlit atrium",
        negative_prompt="grainy",
        input_image="pose_source.png",
        seed=77,
        controlnet_strength=0.65,
        controlnet_end=0.9,
        enhance=True,
    )
    assert params["control_mode"] == "depth", (
        "ComfyUI's DWPose preprocessor loses the person on close-ups and overlapping bodies")
    return params, wf.build_api_payload(params)


def test_sdxl_pose_transfer_reads_depth_off_its_image_and_controls_with_it():
    params, payload = _enhanced_sdxl_pose_transfer_payload()

    load_id = _node_id(payload, "LoadImage")
    scale_id = _node_id(payload, "ImageScaleToTotalPixels")
    getsize_id = _node_id(payload, "GetImageSize")
    assert payload[load_id]["inputs"]["image"] == "pose_source.png"
    assert payload[scale_id]["inputs"]["image"] == [load_id, 0]
    assert payload[scale_id]["inputs"]["megapixels"] == 1.0
    assert payload[scale_id]["inputs"]["resolution_steps"] == 16
    latent = _find_node(payload, "EmptyLatentImage")
    assert latent["inputs"]["width"] == [getsize_id, 0]
    assert latent["inputs"]["height"] == [getsize_id, 1]
    assert latent["inputs"]["batch_size"] == params["batch_size"]

    da_loader_id = _node_id(payload, "DownloadAndLoadDepthAnythingV2Model")
    assert payload[da_loader_id]["inputs"]["model"] == params["depth_model"]
    depth = _find_node(payload, "DepthAnything_V2")
    assert depth["inputs"]["da_model"] == [da_loader_id, 0]
    assert depth["inputs"]["images"] == [scale_id, 0]
    depth_id = _node_id(payload, "DepthAnything_V2")
    assert _find_node(payload, "DWPreprocessor") is None
    cn_loader_id = _node_id(payload, "ControlNetLoader")
    assert payload[cn_loader_id]["inputs"]["control_net_name"] == params["controlnet"]
    union_id = _node_id(payload, "SetUnionControlNetType")
    assert payload[union_id]["inputs"]["control_net"] == [cn_loader_id, 0]
    assert payload[union_id]["inputs"]["type"] == "depth"
    apply = _find_node(payload, "ControlNetApplyAdvanced")
    assert apply["inputs"]["control_net"] == [union_id, 0]
    assert apply["inputs"]["image"] == [depth_id, 0]
    assert apply["inputs"]["strength"] == 0.65
    assert apply["inputs"]["start_percent"] == 0.0
    assert apply["inputs"]["end_percent"] == 0.9


def test_sdxl_pose_transfer_samples_through_its_control_and_saves_the_final_decode():
    params, payload = _enhanced_sdxl_pose_transfer_payload()
    apply = _find_node(payload, "ControlNetApplyAdvanced")

    encodes = {
        n["inputs"]["text"]: nid for nid, n in payload.items()
        if n["class_type"] == "CLIPTextEncode"
    }
    apply_id = _node_id(payload, "ControlNetApplyAdvanced")
    assert apply["inputs"]["positive"] == [encodes["a figure in a sunlit atrium"], 0]
    assert apply["inputs"]["negative"] == [encodes["grainy"], 0]
    sampler = _find_node(payload, "KSampler")
    assert sampler["inputs"]["positive"] == [apply_id, 0]
    assert sampler["inputs"]["negative"] == [apply_id, 1]
    assert sampler["inputs"]["seed"] == 77
    assert sampler["inputs"]["denoise"] == 1.0
    ckpt = _find_node(payload, "CheckpointLoaderSimple")
    assert ckpt["inputs"]["ckpt_name"] == params["checkpoint"]

    decode_id = _node_id(payload, "VAEDecode")
    vae_id = _node_id(payload, "VAELoader")
    assert payload[decode_id]["inputs"]["vae"] == [vae_id, 0]
    assert _find_node(payload, "ImageUpscaleWithModel")["inputs"]["image"] == [decode_id, 0]
    save = _find_node(payload, "SaveImage")
    final_decode = payload[save["inputs"]["images"][0]]
    assert final_decode["class_type"] == "VAEDecode"
    assert final_decode["inputs"]["vae"] == [vae_id, 0]
    assert save["inputs"]["filename_prefix"] == params["filename_prefix"]


def test_sdxl_pose_transfer_size_override_replaces_the_in_graph_derivation():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(wf.default_params(), input_image="x.png", width=1152, height=896)
    payload = wf.build_api_payload(params)

    assert _find_node(payload, "ImageScaleToTotalPixels") is None
    assert _find_node(payload, "GetImageSize") is None
    scale_id = _node_id(payload, "ImageScale")
    load_id = _node_id(payload, "LoadImage")
    assert payload[scale_id]["inputs"] == {
        "image": [load_id, 0], "upscale_method": "lanczos",
        "width": 1152, "height": 896, "crop": "disabled",
    }
    latent = _find_node(payload, "EmptyLatentImage")
    assert latent["inputs"]["width"] == 1152
    assert latent["inputs"]["height"] == 896
    assert _find_node(payload, "DepthAnything_V2")["inputs"]["images"] == [scale_id, 0]


def test_sdxl_pose_transfer_enhances_under_the_same_control():
    _, payload = _enhanced_sdxl_pose_transfer_payload()
    apply_id = _node_id(payload, "ControlNetApplyAdvanced")

    samplers = _nodes_of(payload, "KSampler")

    assert len(samplers) == 2
    assert all(sampler["inputs"]["positive"] == [apply_id, 0] for sampler in samplers), (
        "an enhance re-sampled off the control could drift from the structure map")


def test_sdxl_pose_transfer_draws_at_the_shape_its_structure_map_was_read_at():
    _, payload = _enhanced_sdxl_pose_transfer_payload()
    scaled = [_node_id(payload, "ImageScaleToTotalPixels"), 0]
    measured = _node_id(payload, "GetImageSize")
    latent = _find_node(payload, "EmptyLatentImage")["inputs"]

    assert _find_node(payload, "DepthAnything_V2")["inputs"]["images"] == scaled
    assert payload[measured]["inputs"]["image"] == scaled
    assert (latent["width"], latent["height"]) == ([measured, 0], [measured, 1]), (
        "the map is stretched to the canvas, so a size of another shape "
        "would distort the structure it is there to keep")


def test_the_structure_model_offers_no_sd15_controlnet(installed_models):
    installed_models.add("controlnet", "for_sdxl.safetensors", arch="sdxl")
    installed_models.add("controlnet", "for_sd15.safetensors", arch="sd15")
    by_key = {pd.key: pd for pd in WORKFLOW_REGISTRY["sdxl_pose_transfer"].param_definitions()}

    assert by_key["controlnet"].options == ["for_sdxl.safetensors"], (
        "a ControlNet is built against one UNet's block shapes, "
        "so an SD1.5 one fails outright on an SDXL model")


def test_the_pose_transfers_base_save_sits_clear_of_its_structure_nodes():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    asked = dict(wf.default_params(), input_image="a.png", enhance=True)

    by_depth = wf.build_api_payload(asked)
    by_pose = wf.build_api_payload(dict(asked, control_mode="pose"))

    for payload in (by_depth, by_pose):
        assert payload[wf.base_output_node_id]["class_type"] == "SaveImage"
        assert len(_nodes_of(payload, "SetUnionControlNetType")) == 1
    assert len(_nodes_of(by_depth, "DepthAnything_V2")) == 1
    assert len(_nodes_of(by_depth, "DownloadAndLoadDepthAnythingV2Model")) == 1


def test_every_workflows_output_node_is_the_node_that_saves():
    saving = {"SaveImage", "VHS_VideoCombine"}
    for name, wf in WORKFLOW_REGISTRY.items():
        payload = wf.build_api_payload(dict(wf.default_params(), input_image="a.png",
                                            pose_image="b.png"))
        assert payload[wf.output_node_id]["class_type"] in saving, (
            f"{name}: ComfyUI's history lists a run's files under the node that saved them")


def test_sdxl_pose_transfer_derived_display_size_uses_the_sdxl_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "tall.png", (1080, 1920))

    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(wf.default_params(), input_image="tall.png")
    derived = wf.derived_display_size(params)
    assert derived == scale_to_total_pixels(1080, 1920, megapixels=1.0)
    width, height = derived
    assert 0.9 * 1024 * 1024 <= width * height <= 1.1 * 1024 * 1024


def test_sdxl_pose_transfer_pose_mode_swaps_depth_for_a_dwpose_skeleton():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(wf.default_params(), input_image="x.png", control_mode="pose")
    payload = wf.build_api_payload(params)

    scale_id = _node_id(payload, "ImageScaleToTotalPixels")
    pose = _find_node(payload, "DWPreprocessor")
    assert pose["inputs"]["image"] == [scale_id, 0]
    assert pose["inputs"]["bbox_detector"] == params["pose_bbox_detector"]
    assert pose["inputs"]["pose_estimator"] == params["pose_estimator"]
    assert _find_node(payload, "DepthAnything_V2") is None
    assert _find_node(payload, "DownloadAndLoadDepthAnythingV2Model") is None
    union = _find_node(payload, "SetUnionControlNetType")
    assert union["inputs"]["type"] == "openpose"
    pose_id = _node_id(payload, "DWPreprocessor")
    assert _find_node(payload, "ControlNetApplyAdvanced")["inputs"]["image"] == [pose_id, 0]


def test_sdxl_pose_transfer_scales_pose_sticks_for_xinsir_controlnets():
    # ComfyUI's xinsir pose ControlNets were trained on thicker skeleton sticks than the OpenPose standard.
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(wf.default_params(), input_image="x.png", control_mode="pose")
    assert "xinsir" in params["controlnet"].lower()

    pose = _find_node(wf.build_api_payload(params), "DWPreprocessor")
    assert pose["inputs"]["scale_stick_for_xinsr_cn"] == "enable"

    other = dict(params, controlnet="OpenPoseXL2.safetensors")
    pose = _find_node(wf.build_api_payload(other), "DWPreprocessor")
    assert pose["inputs"]["scale_stick_for_xinsr_cn"] == "disable"


def test_sdxl_pose_transfer_union_type_node_only_wraps_union_controlnets():
    # ComfyUI's plain single-purpose ControlNet crashes on SetUnionControlNetType's extra argument.
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(
        wf.default_params(), input_image="x.png", control_mode="pose",
        controlnet="xinsir_openpose_sdxl_1.0.safetensors",
    )
    payload = wf.build_api_payload(params)
    assert _find_node(payload, "SetUnionControlNetType") is None
    cn_loader_id = _node_id(payload, "ControlNetLoader")
    apply = _find_node(payload, "ControlNetApplyAdvanced")
    assert apply["inputs"]["control_net"] == [cn_loader_id, 0]


def test_a_controlnet_builds_under_its_callers_ids_with_the_head_the_caller_names():
    nodes, ref = WorkflowTemplate.controlnet_nodes(
        "cn", "cn_head", controlnet="a_union_controlnet.safetensors", head="tile")
    assert ref == ["cn_head", 0]
    assert nodes == {
        "cn": {"class_type": "ControlNetLoader",
               "inputs": {"control_net_name": "a_union_controlnet.safetensors"}},
        "cn_head": {"class_type": "SetUnionControlNetType",
                    "inputs": {"control_net": ["cn", 0], "type": "tile"}},
    }

    nodes, ref = WorkflowTemplate.controlnet_nodes(
        "cn", "cn_head", controlnet="a_tile_controlnet.safetensors", head="tile")
    assert ref == ["cn", 0]
    assert list(nodes) == ["cn"]


def test_sdxl_pose_transfer_extract_output_info():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    save_id = next(
        nid for nid, node in wf.build_api_payload(wf.default_params()).items()
        if node["class_type"] == "SaveImage"
    )
    assert wf.output_node_id == save_id
    history = {
        "outputs": {
            save_id: {
                "images": [
                    {"filename": "sdxl_pose_transfer_00001_.png",
                     "subfolder": "image", "type": "output"}
                ]
            }
        }
    }
    files = wf.extract_output_info(history)
    assert len(files) == 1
    assert files[0]["filename"] == "sdxl_pose_transfer_00001_.png"


def test_wan22_t2i_is_registered_as_an_image_workflow():
    assert WORKFLOW_REGISTRY["wan22_t2i"].__class__ is Wan22T2iWorkflow
    wf = Wan22T2iWorkflow()
    assert wf.name == "wan22_t2i"
    assert wf.output_type == "image"
    assert wf.model_keys == ("unet_high", "unet_low")
    assert wf.seed_keys() == ("noise_seed",)


def test_wan22_t2i_default_params_has_required_keys():
    wf = Wan22T2iWorkflow()
    params = wf.default_params()
    required = {
        "positive_prompt", "negative_prompt", "noise_seed", "seed",
        "width", "height", "steps", "cfg", "shift_high", "shift_low",
        "unet_high", "unet_low",
    }
    assert required.issubset(params.keys())


def test_wan22_t2i_build_api_payload_structure():
    wf = Wan22T2iWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "a cat"
    params["negative_prompt"] = "blurry"
    params["noise_seed"] = 42
    params["seed"] = 99
    payload = wf.build_api_payload(params)

    def src(ref):
        return payload[ref[0]]

    latent = _find_node(payload, "EmptyHunyuanLatentVideo")
    assert latent["inputs"]["width"] == params["width"]
    assert latent["inputs"]["height"] == params["height"]
    assert _find_node(payload, "WanImageToVideo") is None
    assert _find_node(payload, "WanFirstLastFrameToVideo") is None
    assert _find_node(payload, "LoadImage") is None
    assert _find_node(payload, "CLIPVisionEncode") is None

    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    assert len(samplers) == 2
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["noise_seed"] == 42
    assert high["inputs"]["end_at_step"] == params["steps"] // 2
    assert low["inputs"]["noise_seed"] == 99
    assert low["inputs"]["start_at_step"] == params["steps"] // 2
    high_id = next(k for k, v in payload.items() if v is high)
    assert low["inputs"]["latent_image"] == [high_id, 0]

    high_unet = src(src(high["inputs"]["model"])["inputs"]["model"])
    low_unet = src(src(low["inputs"]["model"])["inputs"]["model"])
    assert high_unet["inputs"]["unet_name"] == params["unet_high"]
    assert low_unet["inputs"]["unet_name"] == params["unet_low"]

    assert _find_node(payload, "ImageFromBatch") is not None
    save = _find_node(payload, "SaveImage")
    assert save["inputs"]["filename_prefix"] == params["filename_prefix"]
    assert _find_node(payload, "VHS_VideoCombine") is None

    assert any(
        n["class_type"] == "CLIPTextEncode" and n["inputs"]["text"] == "a cat"
        for n in payload.values()
    )
    assert high["inputs"]["positive"] == low["inputs"]["positive"]


def test_wan22_t2i_extract_output_info():
    wf = Wan22T2iWorkflow()
    history = {
        "outputs": {
            "14": {
                "images": [
                    {"filename": "wan22_t2i_00026_.png", "subfolder": "image", "type": "output"}
                ]
            }
        }
    }
    files = wf.extract_output_info(history)
    assert len(files) == 1
    assert files[0]["filename"] == "wan22_t2i_00026_.png"


def test_flux_t2i_upscaled_is_registered_as_an_image_workflow():
    assert WORKFLOW_REGISTRY["flux_t2i_upscaled"].__class__ is FluxT2iUpscaledWorkflow
    wf = FluxT2iUpscaledWorkflow()
    assert wf.name == "flux_t2i_upscaled"
    assert wf.output_type == "image"
    assert wf.model_keys == ("unet",)
    assert wf.seed_keys() == ("seed",)


def test_flux_t2i_upscaled_default_params_has_required_keys():
    wf = FluxT2iUpscaledWorkflow()
    params = wf.default_params()
    required = {
        "positive_prompt", "seed", "steps", "guidance", "width", "height",
        "unet", "clip_name1", "clip_name2", "vae", "upscale_model",
    }
    assert required.issubset(params.keys())
    assert params["guidance"] == 4.5
    assert params["unet"].endswith(".gguf")


def test_flux_t2i_upscaled_exposes_a_gguf_model_dropdown(monkeypatch):
    installed = ["a_flux.gguf", "b_flux.gguf"]
    monkeypatch.setattr(dropdowns, "list_model_files",
                        lambda category, fallback, **terms: installed)

    wf = FluxT2iUpscaledWorkflow()
    by_key = {pd.key: pd for pd in wf.param_definitions()}
    assert "unet" in by_key
    dropdown = by_key["unet"]
    assert dropdown.type == "dropdown"
    assert dropdown.options == installed
    assert dropdown.default == wf.default_params()["unet"]


def test_flux_t2i_upscaled_build_api_payload_structure():
    wf = FluxT2iUpscaledWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "a portrait"
    params["seed"] = 355448440510534
    params["guidance"] = 3.5
    payload = wf.build_api_payload(params)

    unet = _find_node(payload, "UnetLoaderGGUF")
    assert unet["inputs"]["unet_name"] == params["unet"]

    dual = _find_node(payload, "DualCLIPLoader")
    assert dual["inputs"]["type"] == "flux"
    assert dual["inputs"]["clip_name1"] == params["clip_name1"]
    assert dual["inputs"]["clip_name2"] == params["clip_name2"]

    fg = _find_node(payload, "FluxGuidance")
    assert fg["inputs"]["guidance"] == 3.5
    fg_id = _node_id(payload, "FluxGuidance")
    ks = _find_node(payload, "KSampler")
    assert ks["inputs"]["seed"] == 355448440510534
    assert ks["inputs"]["cfg"] == 1.0
    assert ks["inputs"]["positive"] == [fg_id, 0]

    upscale = _find_node(payload, "ImageUpscaleWithModel")
    decode_id = _node_id(payload, "VAEDecode")
    assert upscale["inputs"]["image"] == [decode_id, 0]
    upscale_id = _node_id(payload, "ImageUpscaleWithModel")
    save = _find_node(payload, "SaveImage")
    assert save["inputs"]["images"] == [upscale_id, 0]
    assert save["inputs"]["filename_prefix"] == params["filename_prefix"]
    assert _find_node(payload, "UpscaleModelLoader")["inputs"]["model_name"] == params["upscale_model"]

    assert _find_node(payload, "VRGDG_LLM_Multi") is None


def test_flux_t2i_upscaled_extract_output_info():
    wf = FluxT2iUpscaledWorkflow()
    history = {
        "outputs": {
            wf.output_node_id: {
                "images": [
                    {"filename": "flux_t2i_upscaled_00004_.png", "subfolder": "image", "type": "output"}
                ]
            }
        }
    }
    files = wf.extract_output_info(history)
    assert len(files) == 1
    assert files[0]["filename"] == "flux_t2i_upscaled_00004_.png"


def test_flux_keeps_the_plain_model_upscale_as_its_base_render_under_an_enhance():
    wf = FluxT2iUpscaledWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), enhance=True))

    kept_as_base = payload[wf.base_output_node_id]["inputs"]["images"]

    assert kept_as_base == [_node_id(payload, "ImageUpscaleWithModel"), 0]


def test_no_form_asks_for_what_would_only_be_a_guess():
    the_nodes_own_settings = ("guide_size", "max_size", "feather", "rife", "cache")
    for name, wf in WORKFLOW_REGISTRY.items():
        asked = [pd.key for pd in wf.param_definitions()
                 if any(setting in pd.key for setting in the_nodes_own_settings)]
        assert not asked, (
            f"{name}: the pass already costs the user a tick and a denoise, "
            "and an answer to any of these would be a guess")


def test_every_enhance_capable_workflow_keeps_its_base_render():
    enhancers = [wf for wf in WORKFLOW_REGISTRY.values()
                 if "enhance" in wf.default_params()]
    assert len(enhancers) >= 4
    for wf in enhancers:
        assert wf.base_output_node_id is not None, wf.name
        params = dict(wf.default_params(), enhance=True,
                      input_image="a.png", pose_image="b.png")
        saves = [
            node["inputs"]["filename_prefix"]
            for node in wf.build_api_payload(params).values()
            if node.get("class_type") == "SaveImage"
        ]
        assert f"{params['filename_prefix']}_base" in saves, (
            f"{wf.name}: the base is made on the way and would otherwise be thrown away, "
            "leaving the image no original")
        history = {"outputs": {
            wf.output_node_id: {"images": [{"filename": "enhanced.png"}]},
            wf.base_output_node_id: {"images": [{"filename": "base.png"}]},
        }}
        assert [(f["filename"], f.get("role")) for f in wf.extract_output_info(history)] \
            == [("enhanced.png", None), ("base.png", "original")], wf.name


def test_a_workflow_with_the_tail_off_saves_only_its_own_render():
    for wf in WORKFLOW_REGISTRY.values():
        if "enhance" not in wf.default_params():
            continue
        params = dict(wf.default_params(), enhance=False,
                      input_image="a.png", pose_image="b.png")
        saves = [node for node in wf.build_api_payload(params).values()
                 if node.get("class_type") == "SaveImage"]
        assert len(saves) == 1, wf.name


READS_AS = {
    "sdxl_t2i": "sdxl_t2i",
    "flux_t2i_upscaled": "flux_t2i_upscaled",
    "krea2_t2i": "krea2_t2i",
    "wan22_t2i": "wan22_t2i",
    "wan22_flf2v_loop": "wan22_flf2v_loop",
    "wan22_i2v": "wan22_i2v",
    "sdxl_pose_transfer": "sdxl_t2i",
    "image_enhance": "sdxl_t2i",
    "wan22_animate": "wan22_animate",
}


def test_every_registered_workflow_says_what_its_own_graph_reads_as():
    assert set(READS_AS) == set(WORKFLOW_REGISTRY)


@pytest.mark.parametrize("name", sorted(READS_AS))
def test_a_workflows_own_graph_reads_as_it_always_has(name):
    workflow = WORKFLOW_REGISTRY[name]
    graph = workflow.build_api_payload(dict(workflow.default_params()))

    assert _workflow_from_nodes(graph) == READS_AS[name]


def test_the_graph_signatures_only_ever_name_a_registered_workflow():
    assert {name for name, _ in _GRAPH_SIGNATURES} <= set(WORKFLOW_REGISTRY), (
        "the name is stored into every row, and one no workflow has "
        "names a folder the gallery never builds")



@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_a_video_workflow_offers_its_length_in_seconds_and_reachable_frame_rates(name):
    defs = {pd.key: pd for pd in WORKFLOW_REGISTRY[name].param_definitions()}
    frames, rate = defs["frame_count"], defs["frame_rate"]
    assert frames.shown_in_seconds_at == NATIVE_FPS
    assert frames.options == [1, 5, 10, 15, 30, 60]
    assert frames.unit == "s"
    assert (frames.min_val, frames.step) == (5, 4), (
        "the options are seconds, while the minimum, maximum and step stay frames")
    assert rate.options == [16, 32, 48, 64, 80, 96, 112]
    assert all(playback_rate(r) == r for r in rate.options)
    assert rate.unit == "fps"
    assert (rate.min_val, rate.step) == (NATIVE_FPS, NATIVE_FPS)
    assert rate.max_val == MAX_PLAYBACK_FPS == max(rate.options)


@pytest.mark.parametrize("name", ["wan22_i2v", "wan22_flf2v_loop"])
def test_a_wan22_clip_reaches_the_longest_duration_the_form_offers(name):
    defs = {pd.key: pd for pd in WORKFLOW_REGISTRY[name].param_definitions()}
    frames = defs["frame_count"]
    assert seconds_for_frames(frames.max_val, NATIVE_FPS, frames) == max(DURATION_OPTIONS)


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_a_video_workflow_takes_up_to_a_hundred_steps(name):
    defs = {pd.key: pd for pd in WORKFLOW_REGISTRY[name].param_definitions()}
    assert defs["steps"].max_val == 100, (
        "more steps cost only time, and a count the machine can finish is nothing the form should refuse")
    if "split_step" in defs:
        assert defs["split_step"].max_val == defs["steps"].max_val


def _segments(payload: dict, conditioning: str) -> list[dict]:
    nodes = [n for n in payload.values() if n["class_type"] == conditioning]

    def position(node):
        start = payload[node["inputs"]["start_image"][0]]
        if start["class_type"] != "ImageFromBatch":
            return 0
        decode = payload[start["inputs"]["image"][0]]
        low = payload[decode["inputs"]["samples"][0]]
        high = payload[low["inputs"]["latent_image"][0]]
        return 1 + position(payload[high["inputs"]["latent_image"][0]])

    return sorted(nodes, key=position)


@pytest.mark.parametrize("name", ["wan22_i2v", "wan22_flf2v_loop"])
def test_a_clip_that_fits_one_segment_renders_on_the_graph_it_always_has(name):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(wf.default_params(), frame_count=SINGLE_WINDOW_FRAMES))
    kinds = [n["class_type"] for n in payload.values()]
    assert kinds.count("KSamplerAdvanced") == 2
    assert "ImageFromBatch" not in kinds
    assert "ImageBatch" not in kinds


def test_a_wan22_i2v_clip_longer_than_one_window_is_chained_from_its_last_frame():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), frame_count=481))
    segments = _segments(payload, "WanImageToVideo")
    assert [seg["inputs"]["length"] for seg in segments] == [161, 161, 161]
    for segment in segments[1:]:
        last = payload[segment["inputs"]["start_image"][0]]
        assert last["class_type"] == "ImageFromBatch", (
            "each segment starts from the last frame the one before it decoded, "
            "since windows blended over each other crossfade and drift")
        assert (last["inputs"]["batch_index"], last["inputs"]["length"]) == (160, 1)
        clip_vision = payload[segment["inputs"]["clip_vision_output"][0]]
        assert clip_vision["inputs"]["image"] == segment["inputs"]["start_image"]


def test_a_wan22_loop_longer_than_one_window_is_chained_and_closes_on_its_start_frame():
    wf = Wan22Flf2vLoopWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), frame_count=481))
    segments = _segments(payload, "WanFirstLastFrameToVideo")
    assert [seg["inputs"]["length"] for seg in segments] == [161, 161, 161]
    start = segments[0]["inputs"]["start_image"]
    assert "end_image" not in segments[0]["inputs"], (
        "an earlier segment ending on the start image would close the loop early and have to leave it again")
    assert "end_image" not in segments[1]["inputs"]
    assert segments[2]["inputs"]["end_image"] == start
    for segment in segments[1:]:
        last = payload[segment["inputs"]["start_image"][0]]
        assert (last["class_type"], last["inputs"]["batch_index"], last["inputs"]["length"]) == ("ImageFromBatch", 160, 1)


def test_a_chained_clip_hands_the_writer_every_frame_once_in_order():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), frame_count=481))
    written = payload[wf.output_node_id]["inputs"]["images"]
    joined = payload[written[0]]
    pieces = []
    while joined["class_type"] == "ImageBatch":
        new = payload[joined["inputs"]["image2"][0]]
        assert (new["class_type"], new["inputs"]["batch_index"]) == ("ImageFromBatch", 1)
        pieces.insert(0, new["inputs"]["length"])
        joined = payload[joined["inputs"]["image1"][0]]
    assert joined["class_type"] == "VAEDecode"
    first = payload[payload[payload[joined["inputs"]["samples"][0]]["inputs"]["latent_image"][0]]["inputs"]["latent_image"][0]]
    assert [first["inputs"]["length"], *pieces] == [161, 160, 160]
    assert _find_node(payload, "HunyuanFoleySampler")["inputs"]["image"] == written


def test_each_chained_segment_draws_its_own_noise():
    wf = Wan22I2vWorkflow()
    params = dict(wf.default_params(), frame_count=481, noise_seed=1000, seed=2000)
    payload = wf.build_api_payload(params)
    highs = sorted(n["inputs"]["noise_seed"] for n in payload.values()
                   if n["class_type"] == "KSamplerAdvanced" and n["inputs"]["add_noise"] == "enable")
    lows = sorted(n["inputs"]["noise_seed"] for n in payload.values()
                  if n["class_type"] == "KSamplerAdvanced" and n["inputs"]["add_noise"] == "disable")
    assert highs == [1000, 1001, 1002], (
        "one seed on every segment would replay the same motion from each new start frame, "
        "and stepping the stored seed still reproduces the run from the pair its row records")
    assert lows == [2000, 2001, 2002]


def test_segment_lengths_stay_on_the_models_frame_grid():
    lengths = WorkflowTemplate.segment_lengths
    assert lengths(21) == [21]
    assert lengths(161) == [161]
    assert lengths(165) == [161, 5]
    assert lengths(241) == [161, 81]
    assert lengths(481) == [161, 161, 161]
    for count in range(5, 482, 4):
        parts = lengths(count)
        assert parts[0] + sum(n - 1 for n in parts[1:]) == count
        assert all(n % 4 == 1 and 5 <= n <= 161 for n in parts), count


def test_a_story_its_last_scene_cannot_shorten_enough_shortens_the_scene_before_it():
    assert chained_to(161, [161, 81], shortest=5) == [157, 5]


def test_a_story_too_short_for_its_good_range_lengthens_its_last_scene():
    assert chained_to(81, [5, 5], shortest=5) == [5, 77]


def test_the_last_scene_carries_on_through_the_scenes_after_it():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(
        wf.default_params(), frame_count=481, scene_frames=[161, 161, 161],
        positive_prompt="she waves\n---\nshe turns away"))
    assert _scene_texts(payload, "WanImageToVideo") == ["she waves", "she turns away", "she turns away"]


def test_a_prompt_without_a_scene_break_is_encoded_once_for_every_segment():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(
        wf.default_params(), frame_count=481, positive_prompt="  she waves, slowly  "))
    segments = _segments(payload, "WanImageToVideo")
    assert len({seg["inputs"]["positive"][0] for seg in segments}) == 1
    assert payload[segments[0]["inputs"]["positive"][0]]["inputs"]["text"] == "  she waves, slowly  "


def _scene_texts(payload, conditioning):
    return [payload[seg["inputs"]["positive"][0]]["inputs"]["text"]
            for seg in _segments(payload, conditioning)]


def _scene_negatives(payload, conditioning):
    return [payload[seg["inputs"]["negative"][0]]["inputs"]["text"]
            for seg in _segments(payload, conditioning)]


@pytest.mark.parametrize(("name", "conditioning"), [
    ("wan22_i2v", "WanImageToVideo"), ("wan22_flf2v_loop", "WanFirstLastFrameToVideo"),
])
def test_each_scene_keeps_out_its_own_negative(name, conditioning):
    wf = WORKFLOW_REGISTRY[name]
    params = dict(wf.default_params(), frame_count=401, scene_frames=[161, 81, 161],
                  positive_prompt="a\n---\nb\n---\nc")
    payload = wf.build_api_payload(dict(params, negative_prompt="no hats\n---\nno hands"))
    assert _scene_negatives(payload, conditioning) == ["no hats", "no hands", "no hands"]
    payload = wf.build_api_payload(dict(params, negative_prompt="blurry"))
    refs = [seg["inputs"]["negative"] for seg in _segments(payload, conditioning)]
    assert refs[0] == refs[1] == refs[2]
    assert _scene_negatives(payload, conditioning) == ["blurry"] * 3


@pytest.mark.parametrize(("name", "conditioning"), [
    ("wan22_i2v", "WanImageToVideo"), ("wan22_flf2v_loop", "WanFirstLastFrameToVideo"),
])
def test_each_scene_runs_for_its_own_frames_and_reads_its_own_prompt(name, conditioning):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(
        wf.default_params(), frame_count=401, scene_frames=[161, 81, 161],
        positive_prompt="she waves\n---\nshe turns\n---\nshe walks off"))
    segments = _segments(payload, conditioning)
    assert [seg["inputs"]["length"] for seg in segments] == [161, 81, 161]
    assert _scene_texts(payload, conditioning) == ["she waves", "she turns", "she walks off"]
    assert _find_node(payload, "HunyuanFoleySampler")["inputs"]["duration"] == pytest.approx(401 / 16)


def test_a_scene_longer_than_one_window_is_two_segments_of_the_same_scene():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(
        wf.default_params(), frame_count=321, scene_frames=[241, 81],
        positive_prompt="she waves\n---\nshe turns"))
    assert [seg["inputs"]["length"] for seg in _segments(payload, "WanImageToVideo")] == [161, 81, 81]
    assert _scene_texts(payload, "WanImageToVideo") == ["she waves", "she waves", "she turns"]


def test_a_lone_scene_runs_for_the_clip_length_whatever_its_own_entry_says():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), frame_count=121, scene_frames=[81]))
    assert [seg["inputs"]["length"] for seg in _segments(payload, "WanImageToVideo")] == [121], (
        "every other reader of the settings goes by the video's length, "
        "and settings carried in from the overlay hold nothing else")


@pytest.mark.parametrize("wf", [Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()],
                         ids=lambda wf: wf.name)
def test_the_audio_is_scored_for_the_scenes_as_they_add_up(wf):
    payload = wf.build_api_payload(dict(
        wf.default_params(), frame_count=481, scene_frames=[161, 81],
        positive_prompt="a\n---\nb"))
    assert _find_node(payload, "HunyuanFoleySampler")["inputs"]["duration"] == pytest.approx(241 / 16)



@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_every_video_is_saved_as_h264_at_one_high_quality(name):
    wf = WORKFLOW_REGISTRY[name]
    params = wf.default_params()
    writer = wf.build_api_payload(params)[wf.output_node_id]

    assert writer["class_type"] == "VHS_VideoCombine"
    inputs = writer["inputs"]
    assert (inputs["format"], inputs["pix_fmt"], inputs["crf"]) == ("video/h264-mp4", "yuv420p", 13)
    assert inputs["filename_prefix"] == params["filename_prefix"]



@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_a_clip_played_at_the_native_rate_carries_no_interpolation_at_all(name):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(wf.default_params(), frame_rate=NATIVE_FPS))

    assert _find_node(payload, "RIFE VFI") is None
    writer = payload[wf.output_node_id]["inputs"]
    assert writer["images"] == [_node_id(payload, "VAEDecode"), 0]
    assert writer["frame_rate"] == 16.0


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_a_higher_rate_interpolates_the_decoded_frames_and_writes_at_that_rate(name):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(wf.default_params(), frame_rate=48.0))

    rife_id = _node_id(payload, "RIFE VFI")
    rife = payload[rife_id]["inputs"]
    assert rife["frames"] == [_node_id(payload, "VAEDecode"), 0]
    assert rife["multiplier"] == 3
    assert rife["ckpt_name"] == RIFE_CHECKPOINT

    writer = payload[wf.output_node_id]["inputs"]
    assert writer["images"] == [rife_id, 0]
    assert writer["frame_rate"] == 48.0


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_the_frames_a_clip_generates_dont_move_when_its_rate_does(name):
    wf = WORKFLOW_REGISTRY[name]
    lengths = set()
    for rate in (16.0, 32.0, 128.0):
        payload = wf.build_api_payload(dict(wf.default_params(), frame_rate=rate))
        conditioning = (_find_node(payload, "WanImageToVideo")
                        or _find_node(payload, "WanFirstLastFrameToVideo")
                        or _find_node(payload, "WanAnimateToVideo"))
        lengths.add(conditioning["inputs"]["length"])
    assert lengths == {wf.default_params()["frame_count"]}


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_a_rate_between_two_multiples_is_written_at_the_one_it_can_reach(name):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(wf.default_params(), frame_rate=60.0))

    assert payload[_node_id(payload, "RIFE VFI")]["inputs"]["multiplier"] == 4
    assert payload[wf.output_node_id]["inputs"]["frame_rate"] == 64.0


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_no_payload_writes_faster_than_the_fastest_rate_the_form_offers(name):
    wf = WORKFLOW_REGISTRY[name]
    for asked in (128.0, 240.0, 10_000.0):
        payload = wf.build_api_payload(dict(wf.default_params(), frame_rate=asked))
        assert payload[wf.output_node_id]["inputs"]["frame_rate"] == MAX_PLAYBACK_FPS
        assert payload[_node_id(payload, "RIFE VFI")]["inputs"]["multiplier"] == 7


@pytest.mark.parametrize("name", _SCORED_VIDEO_WORKFLOWS)
def test_the_soundtrack_stays_the_clips_real_length_at_every_rate(name):
    wf = WORKFLOW_REGISTRY[name]
    params = dict(wf.default_params(), frame_count=81, frame_rate=MAX_PLAYBACK_FPS)
    payload = wf.build_api_payload(params)

    sampler = _find_node(payload, "HunyuanFoleySampler")["inputs"]
    assert sampler["image"] == [_node_id(payload, "VAEDecode"), 0]
    assert sampler["frame_rate"] == NATIVE_FPS
    assert sampler["duration"] == pytest.approx(81 / NATIVE_FPS)


def test_a_loops_two_matched_ends_survive_the_frames_added_between_them():
    wf = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    payload = wf.build_api_payload(
        dict(wf.default_params(), frame_count=81, frame_rate=64.0))

    combine = _find_node(payload, "VHS_VideoCombine")["inputs"]
    assert combine["loop_count"] == 0
    assert combine["pingpong"] is False
    multiplier = payload[_node_id(payload, "RIFE VFI")]["inputs"]["multiplier"]
    assert (81 - 1) * multiplier + 1 == 321
    interpolated_span = (321 - 1) / 64.0
    assert interpolated_span == pytest.approx((81 - 1) / NATIVE_FPS)


@pytest.mark.parametrize("name", _VIDEO_WORKFLOWS)
def test_the_rate_the_form_settles_on_is_the_rate_the_file_gets(name):
    rate_def = next(pd for pd in WORKFLOW_REGISTRY[name].param_definitions()
                    if pd.key == "frame_rate")
    for typed in range(200):
        shown = clamped_number(rate_def, float(typed))
        assert shown == min(rate_def.max_val, playback_rate(typed)), typed
        assert clamped_number(rate_def, shown) == shown


_GRAPH_JARGON = re.compile(
    r"CFG|Denoise|Stage|Guidance|Input Image|ControlNet|Scheduler|Shift"
    r"|\((High|Low|Speech)\)|Audio|\(Hz\)|\(End %\)|\(0 = half\)|\b[XY]\b"
)

_NAMES_EVERYONE_USES = {
    "positive_prompt": "Positive Prompt",
    "negative_prompt": "Negative Prompt",
    "audio_prompt": "Positive Prompt",
    "audio_negative_prompt": "Negative Prompt",
    "lora_high": "LoRA 1 (First Pass)",
    "lora_strength_high": "LoRA Strength 1 (First Pass)",
    "lora_low": "LoRA 1 (Second Pass)",
    "lora_strength_low": "LoRA Strength 1 (Second Pass)",
    "sampler_name": "Sampler",
}


@pytest.mark.parametrize("name", list(WORKFLOW_REGISTRY))
def test_form_labels_say_what_a_setting_does_not_what_the_graph_calls_it(name):
    labels = [pd.label for pd in WORKFLOW_REGISTRY[name].param_definitions()]
    assert [label for label in labels if _GRAPH_JARGON.search(label)] == []


@pytest.mark.parametrize("name", list(WORKFLOW_REGISTRY))
def test_the_prompts_loras_and_sampler_keep_the_names_everyone_already_uses(name):
    labels = {pd.key: pd.label for pd in WORKFLOW_REGISTRY[name].param_definitions()}
    named = {key: labels[key] for key in labels.keys() & _NAMES_EVERYONE_USES.keys()}
    assert named == {key: _NAMES_EVERYONE_USES[key] for key in named}


@pytest.mark.parametrize("name", ["wan22_t2i", "wan22_flf2v_loop", "wan22_i2v"])
def test_a_wan_2_2_form_offers_one_composition_focus_for_both_passes(name):
    focus = [(pd.label, pd.key, pd.also_sets) for pd in WORKFLOW_REGISTRY[name].param_definitions()
             if pd.label.startswith("Composition Focus")]
    assert focus == [("Composition Focus", "shift_high", ("shift_low",))], (
        "two values would hand the result over between the passes at mismatched noise")


@pytest.mark.parametrize("name", list(WORKFLOW_REGISTRY))
def test_a_workflow_name_uses_no_model_tile_shorthand_but_t2i_i2v_and_t2v(name):
    assert not re.search(r"\b(FLF2V|ATI|I2I|S2V)\b", WORKFLOW_REGISTRY[name].display_name)


def test_wan22_i2v_stages_take_their_own_prompt_strength_with_no_shared_one():
    wf = Wan22I2vWorkflow()
    keys = [pd.key for pd in wf.param_definitions()]
    assert "cfg" not in keys
    assert "cfg" not in wf.default_params()

    params = dict(wf.default_params(), steps=24, split_step=3,
                  cfg_high=2.0, cfg_low=6.0)
    payload = wf.build_api_payload(params)
    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["end_at_step"] == 3
    assert low["inputs"]["start_at_step"] == 3
    assert high["inputs"]["cfg"] == 2.0
    assert low["inputs"]["cfg"] == 6.0


@pytest.mark.parametrize("name", ["wan22_t2i", "wan22_flf2v_loop", "wan22_i2v"])
def test_a_wan_2_2_form_offers_no_seed_for_the_pass_that_draws_no_new_noise(name):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(wf.default_params(), input_image="example_start.png"))
    second_passes = [node["inputs"] for node in payload.values()
                     if node["class_type"] == "KSamplerAdvanced"
                     and node["inputs"]["add_noise"] == "disable"]

    assert second_passes
    assert all(p["sampler_name"] == "euler" for p in second_passes)
    assert "seed" not in {pd.key for pd in wf.param_definitions()}


def test_a_part_with_an_outline_is_redrawn_inside_it_rather_than_in_a_box_around_it():
    payload = _enhance_payload(outlined=["skin_finder.pt"], enhance_detail_fixes={"skin": 0.4})

    (detailer,) = _nodes_of(payload, "DetailerForEach")
    segs = payload[detailer["inputs"]["segs"][0]]
    assert segs["class_type"] == "SegmDetectorSEGS", (
        "a box around the hair takes the face with it, and a box around the skin is most of the image")
    provider_id, output = segs["inputs"]["segm_detector"]
    assert payload[provider_id]["class_type"] == "UltralyticsDetectorProvider"
    assert output == 1
    assert payload[provider_id]["inputs"]["model_name"] == "segm/skin_finder.pt"
    assert "bbox_detector" not in segs["inputs"]
    assert segs["inputs"]["image"] == detailer["inputs"]["image"]


def test_a_part_with_its_own_prompts_is_redrawn_toward_them_ahead_of_the_images_prompt():
    skin = next(part for part in detail_module.part_table() if part.name == "skin")
    payload = _enhance_payload(
        outlined=["skin_finder.pt"], positive_prompt="a lantern on a jetty",
        negative_prompt="blurry", enhance_detail_fixes={"skin": 0.4},
    )

    (detailer,) = _nodes_of(payload, "DetailerForEach")
    positive = payload[detailer["inputs"]["positive"][0]]
    negative = payload[detailer["inputs"]["negative"][0]]
    assert positive["class_type"] == negative["class_type"] == "CLIPTextEncode"
    assert positive["inputs"]["text"] == f"{skin.prompt}, a lantern on a jetty"
    assert negative["inputs"]["text"] == f"{skin.avoid}, blurry"
    assert positive["inputs"]["clip"] == negative["inputs"]["clip"] == detailer["inputs"]["clip"]
    sampler = _find_node(payload, "KSampler")["inputs"]
    assert payload[sampler["positive"][0]]["inputs"]["text"] == "a lantern on a jetty"
    assert payload[sampler["negative"][0]]["inputs"]["text"] == "blurry"


def test_a_fix_reads_its_own_words_as_a_piece_ahead_of_a_boxed_prompts_boxes():
    payload = _enhance_payload(
        positive_prompt=f"a lantern {BOX_BREAK}on a jetty", negative_prompt="blurry",
        enhance_detail_fixes={"hands": 0.45},
        enhance_fix_prompts={"hands": {"prompt": "open palms", "avoid": "fists"}},
    )

    (detailer,) = _nodes_of(payload, "DetailerForEach")
    assert texts_read(payload, payload[detailer["inputs"]["positive"][0]]) == [
        "open palms", "a lantern ", "on a jetty"]
    assert texts_read(payload, payload[detailer["inputs"]["negative"][0]]) == ["fists, blurry"]
    sampler = _find_node(payload, "KSampler")["inputs"]
    assert texts_read(payload, payload[sampler["positive"][0]]) == ["a lantern ", "on a jetty"]


@pytest.mark.parametrize(("name", "prompt_ids"), [
    ("sdxl_t2i", ("2", "3")), ("sdxl_pose_transfer", ("5", "6")), ("image_enhance", ("3", "4"))])
def test_an_sdxl_graph_reads_each_box_of_a_prompt_on_its_own(name, prompt_ids):
    wf = WORKFLOW_REGISTRY[name]
    payload = wf.build_api_payload(dict(
        wf.default_params(), input_image="pick.png",
        positive_prompt=f"a lantern {BOX_BREAK}on a jetty", negative_prompt=f"blurry {BOX_BREAK}dim"))

    assert [texts_read(payload, payload[node_id]) for node_id in prompt_ids] == [
        ["a lantern ", "on a jetty"], ["blurry ", "dim"]]
    assert BOX_BREAK not in json.dumps(payload)


def test_an_image_with_no_prompt_leaves_a_part_its_own_prompts_alone():
    skin = next(part for part in detail_module.part_table() if part.name == "skin")
    payload = _enhance_payload(outlined=["skin_finder.pt"], positive_prompt="",
                               negative_prompt="", enhance_detail_fixes={"skin": 0.4})

    (detailer,) = _nodes_of(payload, "DetailerForEach")
    assert payload[detailer["inputs"]["positive"][0]]["inputs"]["text"] == skin.prompt
    assert payload[detailer["inputs"]["negative"][0]]["inputs"]["text"] == skin.avoid


def test_a_fix_is_redrawn_toward_the_prompts_its_settings_give_it():
    payload = _enhance_payload(
        positive_prompt="a lantern on a jetty", negative_prompt="blurry",
        enhance_detail_fixes={"hands": 0.45},
        enhance_fix_prompts={"hands": {"prompt": "open palms", "avoid": "fists"}},
    )

    (detailer,) = _nodes_of(payload, "DetailerForEach")
    assert payload[detailer["inputs"]["positive"][0]]["inputs"]["text"] == "open palms, a lantern on a jetty"
    assert payload[detailer["inputs"]["negative"][0]]["inputs"]["text"] == "fists, blurry"


def test_only_a_workflow_with_scenes_tells_a_story():
    assert {name for name, workflow in WORKFLOW_REGISTRY.items() if workflow.tells_a_story()} == {
        "wan22_i2v", "wan22_flf2v_loop"}


def test_a_part_the_enhance_fixes_runs_a_real_denoise_so_the_floor_of_the_range_is_above_zero():
    fixes = next(pd for pd in WORKFLOW_REGISTRY["image_enhance"].param_definitions()
                 if pd.key == "enhance_detail_fixes")

    assert fixes.min_val > 0, "ComfyUI's detailer node refuses a denoise of zero"


def test_a_loops_size_set_by_hand_reaches_both_of_its_ends():
    wf = Wan22Flf2vLoopWorkflow()
    payload = wf.build_api_payload(dict(wf.default_params(), input_image="a.png",
                                        width=640, height=480))
    (segment,) = _segments(payload, "WanFirstLastFrameToVideo")
    scaled = [_node_id(payload, "ImageScale"), 0]

    assert (segment["inputs"]["start_image"], segment["inputs"]["end_image"]) == (scaled, scaled)
    assert (segment["inputs"]["width"], segment["inputs"]["height"]) == (640, 480)


def test_the_speaking_model_sits_between_the_expert_models_and_their_loras():
    keys = [pd.key for pd in Wan22I2vWorkflow().param_definitions()]
    models = [keys.index(key) for key in ("unet_high", "unet_low", "unet_s2v")]
    first_lora = keys.index("lora_high")

    assert max(models) < first_lora, (
        "the rows come in the order the form shows and the gallery groups by: "
        "the models together, then the LoRAs")



def test_a_workflow_works_out_once_whether_it_starts_from_an_image(monkeypatch):
    workflow = Wan22I2vWorkflow()
    asked = []
    real = workflow.default_params
    monkeypatch.setattr(workflow, "default_params", lambda: asked.append(1) or real())

    answers = [workflow.starts_from_an_image() for _ in range(3)]

    assert answers == [True] * 3
    assert len(asked) == 1
