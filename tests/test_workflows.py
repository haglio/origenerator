import json

import pytest

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
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


def test_workflows_declare_the_params_that_identify_their_model():
    # The gallery groups a workflow's generations by these param values, so each
    # workflow names the param(s) that pick its model.
    assert SdxlT2iWorkflow().model_keys == ("checkpoint",)
    assert Wan22I2vWorkflow().model_keys == ("unet_high", "unet_low")
    assert Wan22Flf2vLoopWorkflow().model_keys == ("unet_high", "unet_low")


def test_workflows_declare_the_params_that_identify_their_lora():
    # The gallery nests a workflow's runs by LoRA under model, so the two WAN
    # video workflows name the param(s) that pick their LoRA. Workflows with no
    # LoRA (SDXL, WAN t2i) declare none, and so grow no LoRA folder level.
    assert Wan22I2vWorkflow().lora_keys == ("lora_high", "lora_low")
    assert Wan22Flf2vLoopWorkflow().lora_keys == ("lora_high", "lora_low")
    assert SdxlT2iWorkflow().lora_keys == ()
    assert Wan22T2iWorkflow().lora_keys == ()


def test_only_the_flf2v_workflow_declares_itself_looping():
    # The funscript synthesized alongside a video tiles seamlessly only for a clip
    # that returns to its start, so the loop workflow marks itself looping and the
    # others (a one-shot i2v, the still-image workflows) don't.
    assert Wan22Flf2vLoopWorkflow().looping is True
    assert Wan22I2vWorkflow().looping is False
    assert SdxlT2iWorkflow().looping is False


def test_wan_video_workflows_expose_lora_pickers(monkeypatch):
    # The WAN video workflows pick their LoRA from the installed files, like the
    # SDXL Model dropdown: a combo per high/low LoRA, its options led by "None"
    # (so a run can opt out of a LoRA) then the loras scan, and its default
    # matching the persisted default — not a hidden param the form silently reset
    # to default. Where the pickers sit is asserted separately, by
    # test_wan_video_workflows_group_all_models_then_all_loras.
    import origenerator.workflows.wan22_flf2v_loop as flf
    import origenerator.workflows.wan22_i2v as i2v
    from origenerator.workflows.model_files import NO_LORA

    options = [NO_LORA, "x_high.safetensors", "y_low.safetensors"]
    monkeypatch.setattr(i2v, "list_lora_files", lambda fallback: options)
    monkeypatch.setattr(flf, "list_lora_files", lambda fallback: options)

    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        for level in ("high", "low"):
            picker = by_key[f"lora_{level}"]
            assert picker.type == "combo"
            assert picker.options == options
            assert picker.options[0] == NO_LORA  # a run can bypass the LoRA
            assert picker.default == wf.default_params()[f"lora_{level}"]


def test_wan_video_workflows_bypass_a_none_lora(monkeypatch):
    # Choosing "None" for a LoRA builds the graph with no LoraLoader for that
    # slot: the sampler's model runs straight from the UNET, unmodified. The
    # other stage's real LoRA is untouched. Verified both by the payload (how
    # many LoraLoaderModelOnly nodes it has) and by reading the graph back the
    # way the importer does — a bypassed stage resolves to no LoRA at all.
    from origenerator.comfy_graph import dual_sampler_model_files
    from origenerator.workflows.model_files import NO_LORA

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
        assert "lora_high" not in read           # bypassed → no LoRA on that stage
        assert read["lora_low"] == "lo.safetensors"
        assert read["unet_high"] == base["unet_high"]  # base model still runs

        none = wf.build_api_payload(dict(base, lora_high=NO_LORA, lora_low=NO_LORA))
        assert lora_count(none) == 0
        read = dual_sampler_model_files(none)
        assert "lora_high" not in read and "lora_low" not in read
        assert read["unet_high"] == base["unet_high"]
        assert read["unet_low"] == base["unet_low"]


def test_wan_video_workflows_expose_model_pickers(monkeypatch):
    # The base diffusion model (high/low UNET) is a combo too, drawn from the
    # installed diffusion_models — selectable, not a hidden default the form
    # silently reset. Where the pickers sit is asserted separately, by
    # test_wan_video_workflows_group_all_models_then_all_loras.
    import origenerator.workflows.wan22_flf2v_loop as flf
    import origenerator.workflows.wan22_i2v as i2v

    installed = {
        "diffusion_models": ["m_high.safetensors", "m_low.safetensors"],
        "loras": ["l.safetensors"],
    }
    picker = lambda category, fallback: installed[category]
    monkeypatch.setattr(i2v, "list_model_files", picker)
    monkeypatch.setattr(flf, "list_model_files", picker)

    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        for level in ("high", "low"):
            model = by_key[f"unet_{level}"]
            assert model.type == "combo"
            assert model.options == installed["diffusion_models"]
            assert model.default == wf.default_params()[f"unet_{level}"]


def test_wan_video_workflows_group_all_models_then_all_loras():
    # Model and LoRA settings are grouped by kind, not by noise level: both UNET
    # pickers sit together, then both LoRA pickers (each directly above its own
    # strength). So the Generate form and the gallery info pane read as "all the
    # models, then all the LoRAs" rather than "everything high, then everything
    # low". This order is the single source both surfaces draw from.
    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        keys = [d.key for d in wf.param_definitions()]
        model_block = [keys.index(k) for k in ("unet_high", "unet_low")]
        lora_block = [
            keys.index(k) for k in
            ("lora_high", "lora_strength_high", "lora_low", "lora_strength_low")
        ]
        # Each kind is one contiguous run, in the listed order...
        assert model_block == list(range(model_block[0], model_block[0] + 2))
        assert lora_block == list(range(lora_block[0], lora_block[0] + 4))
        # ...with every model picker above every LoRA picker.
        assert model_block[-1] < lora_block[0]


def test_workflows_expose_their_seed_param_keys():
    # A variation re-rolls exactly these. The video workflows carry a third
    # seed for the foley pass, so a variation re-scores its audio too — the
    # motion changed, so the old track couldn't fit anyway.
    assert SdxlT2iWorkflow().seed_keys() == ("seed",)
    assert Wan22I2vWorkflow().seed_keys() == ("noise_seed", "seed", "audio_seed")
    assert Wan22Flf2vLoopWorkflow().seed_keys() == ("noise_seed", "seed", "audio_seed")


def test_wan_video_workflows_expose_editable_audio_params():
    # The audio prompt/negative/seed are ordinary editable fields (the foley
    # model files stay read-only passthroughs, like clip_name/vae_name): a run
    # can steer what the clip sounds like, or leave the prompt blank to let the
    # foley model score the frames on its own.
    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        prompt = by_key["audio_prompt"]
        assert prompt.type == "str" and prompt.multiline
        assert prompt.default == ""
        negative = by_key["audio_negative_prompt"]
        assert negative.type == "str" and negative.multiline
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


def test_sdxl_t2i_param_definitions_returns_paramdefs():
    wf = SdxlT2iWorkflow()
    defs = wf.param_definitions()
    assert len(defs) > 0
    assert all(isinstance(d, ParamDef) for d in defs)
    keys = [d.key for d in defs]
    assert "positive_prompt" in keys
    assert "seed" in keys


def test_sdxl_t2i_build_api_payload_structure():
    wf = SdxlT2iWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "test prompt"
    params["negative_prompt"] = "bad quality"
    params["seed"] = 42
    payload = wf.build_api_payload(params)
    # Should have node IDs as string keys
    assert isinstance(payload, dict)
    # Node 2 is positive CLIPTextEncode
    assert payload["2"]["class_type"] == "CLIPTextEncode"
    assert payload["2"]["inputs"]["text"] == "test prompt"
    # Node 3 is negative CLIPTextEncode
    assert payload["3"]["inputs"]["text"] == "bad quality"
    # Node 5 is KSampler
    assert payload["5"]["class_type"] == "KSampler"
    assert payload["5"]["inputs"]["seed"] == 42
    assert payload["5"]["inputs"]["steps"] == params["steps"]
    assert payload["5"]["inputs"]["cfg"] == params["cfg"]
    # Node 7 is SaveImage
    assert payload["7"]["class_type"] == "SaveImage"


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


# ---- The upscale/enhance tail (a checkbox on every image workflow) ----

# Every image-producing workflow carries the enhance toggle; these are they.
_ENHANCE_TOGGLE_WORKFLOWS = ("sdxl_t2i", "sdxl_pose_transfer",
                             "flux_t2i_upscaled", "wan22_t2i")


def test_image_workflows_expose_the_enhance_toggle():
    # The tail is an option in the generation controls: a bool (checkbox) param
    # on every image workflow. The SDXL pair keeps it on by default (their
    # established behavior); flux and WAN t2i add it off, preserving theirs.
    defaults = {"sdxl_t2i": True, "sdxl_pose_transfer": True,
                "flux_t2i_upscaled": False, "wan22_t2i": False}
    for name, default in defaults.items():
        wf = WORKFLOW_REGISTRY[name]
        toggle = {pd.key: pd for pd in wf.param_definitions()}["enhance"]
        assert toggle.type == "bool", name
        assert toggle.default is default, name
        assert wf.default_params()["enhance"] is default, name


def test_enhance_toggle_appends_the_tail_on_every_image_workflow():
    # With the checkbox on, every image workflow ends in the shared tail:
    # model upscale -> rescale to enhance_scale x the base (the model is 4x) ->
    # re-encode -> a low-denoise KSampler on the workflow's own model and
    # conditioning -> decode -> save.
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
        scale = payload[scale_id]["inputs"]
        assert scale["image"] == [up_id, 0]
        assert scale["scale_by"] == pytest.approx(2.0 / 4.0)
        encode_id = _node_id(payload, "VAEEncode")
        assert payload[encode_id]["inputs"]["pixels"] == [scale_id, 0]

        sampler = next(n for n in payload.values()
                       if n["class_type"] == "KSampler"
                       and n["inputs"]["latent_image"] == [encode_id, 0])
        sampler_id = next(k for k, v in payload.items() if v is sampler)
        assert sampler["inputs"]["steps"] == 17, name
        assert sampler["inputs"]["denoise"] == 0.35
        assert sampler["inputs"]["seed"] == 11
        assert sampler["inputs"]["cfg"] == params["cfg"]

        save = _find_node(payload, "SaveImage")
        final = payload[save["inputs"]["images"][0]]
        assert final["class_type"] == "VAEDecode", name
        assert final["inputs"]["samples"] == [sampler_id, 0]
        assert final["inputs"]["vae"] == payload[encode_id]["inputs"]["vae"]


def test_enhance_toggle_off_ends_at_the_plain_output():
    # Unchecked, no tail is built: no re-encode, no second low-denoise sampler.
    # Flux keeps its namesake bare 4x upscale; the others save the base output
    # exactly as they did before the toggle existed.
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
    # The WAN tail re-samples on the LOW-noise model's shift chain — the stage
    # WAN 2.2 itself refines with — using the same text conditioning and VAE as
    # the base pass, over the single kept frame.
    wf = WORKFLOW_REGISTRY["wan22_t2i"]
    payload = wf.build_api_payload(dict(wf.default_params(), enhance=True))
    encode_id = _node_id(payload, "VAEEncode")
    sampler = next(n for n in payload.values()
                   if n["class_type"] == "KSampler"
                   and n["inputs"]["latent_image"] == [encode_id, 0])
    low = next(n for n in payload.values()
               if n["class_type"] == "KSamplerAdvanced"
               and n["inputs"]["add_noise"] == "disable")
    assert sampler["inputs"]["model"] == low["inputs"]["model"]
    assert sampler["inputs"]["positive"] == low["inputs"]["positive"]
    assert sampler["inputs"]["negative"] == low["inputs"]["negative"]
    frame_id = _node_id(payload, "ImageFromBatch")
    assert _find_node(payload, "ImageUpscaleWithModel")["inputs"]["image"] == [frame_id, 0]


def test_flux_enhance_resamples_on_the_guided_conditioning():
    # Flux's tail re-samples on the same GGUF model, FluxGuidance-wrapped
    # positive, and its own VAE — cfg stays at Flux's 1.0.
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


# ---- Image Enhance (the standalone form of the tail) ----

def test_image_enhance_is_registered_and_derives_size_from_the_source(tmp_path, monkeypatch):
    from origenerator.workflows.image_enhance import ImageEnhanceWorkflow

    wf = WORKFLOW_REGISTRY["image_enhance"]
    assert wf.__class__ is ImageEnhanceWorkflow
    assert wf.output_type == "image"
    assert wf.model_keys == ("checkpoint",)
    assert wf.seed_keys() == ("seed",)
    # Machinery, not a peer workflow: launched by the gallery's enhance
    # buttons, never offered in the Generate dropdown. Every real workflow is.
    assert wf.selectable is False
    assert all(WORKFLOW_REGISTRY[n].selectable for n in WORKFLOW_REGISTRY
               if n != "image_enhance")
    # It takes an input image, so — like every input-image workflow — its size
    # derives from it: the source's own dimensions at enhance_scale, no budget.
    assert wf.derives_size_from_input is True
    import origenerator.workflows.derived_size as ds
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
    # The SDXL checkpoint does the refining, steered by the prompts.
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
    # Unlocking the derived Dimensions swaps the relative rescale for an exact
    # one, so the override actually governs the saved size.
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


# ---- The SDXL upscale/enhance tail (shared by both SDXL workflows) ----

def test_sdxl_workflows_end_with_an_upscale_enhance_pass():
    # Both SDXL stills workflows finish with a hires-fix tail: the decoded
    # render is model-upscaled (sharpness), rescaled to enhance_scale x the
    # base size (the model itself is 4x, so the rescale is relative to its
    # output), re-encoded, and re-sampled at low denoise — the checkpoint
    # generating real fine texture rather than interpolating pixels, which is
    # what keeps the enlargement naturalistic. SaveImage stores that result.
    for name in ("sdxl_t2i", "sdxl_pose_transfer"):
        wf = WORKFLOW_REGISTRY[name]
        params = dict(wf.default_params(), seed=11, enhance_scale=2.0,
                      enhance_steps=17, enhance_denoise=0.35)
        payload = wf.build_api_payload(params)

        loader_id = _node_id(payload, "UpscaleModelLoader")
        assert payload[loader_id]["inputs"]["model_name"] == params["upscale_model"], name
        up_id = _node_id(payload, "ImageUpscaleWithModel")
        assert payload[up_id]["inputs"]["upscale_model"] == [loader_id, 0]
        scale_id = _node_id(payload, "ImageScaleBy")
        scale = payload[scale_id]["inputs"]
        assert scale["image"] == [up_id, 0]
        assert scale["scale_by"] == pytest.approx(2.0 / 4.0)
        encode_id = _node_id(payload, "VAEEncode")
        assert payload[encode_id]["inputs"]["pixels"] == [scale_id, 0]

        # Two samplers: the base pass and the enhance pass over the re-encoded
        # image. The enhance pass runs its own steps/denoise but reuses the
        # base pass's model, conditioning, cfg and seed — same recipe, refined.
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

        # The tail hangs off the BASE pass's decode, and SaveImage stores the
        # enhance pass's decode, both through the workflow's one VAE.
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


def test_sdxl_workflows_expose_the_enhance_knobs(monkeypatch):
    # The enhance tail's look-affecting knobs are ordinary form fields: the
    # upscale model picked from the installed upscale_models files like every
    # other model picker, and the scale/steps/denoise numerics — not hidden
    # defaults the form would silently reset.
    import origenerator.workflows.sdxl_pose_transfer as pose
    import origenerator.workflows.sdxl_t2i as t2i

    installed = {"upscale_models": ["4x_crisp.pt", "4x_soft.pth"]}
    picker = lambda category, fallback: installed.get(category, list(fallback))
    monkeypatch.setattr(t2i, "list_model_files", picker)
    monkeypatch.setattr(pose, "list_model_files", picker)

    for name in ("sdxl_t2i", "sdxl_pose_transfer"):
        wf = WORKFLOW_REGISTRY[name]
        by_key = {pd.key: pd for pd in wf.param_definitions()}
        model = by_key["upscale_model"]
        assert model.type == "combo"
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
        # Low by design: 0.3 re-imagined creases into wounds/disfigurements.
        assert denoise.default == 0.15


def test_enhance_keys_cover_every_param_only_the_tail_reads():
    # The gallery drops these from a row's identity, so an enhanced render shares
    # its unenhanced twin's folder. A tail param left off the list would silently
    # split that folder again, so every workflow's list must cover its whole tail.
    for name in ("sdxl_t2i", "sdxl_pose_transfer", "wan22_t2i"):
        wf = WORKFLOW_REGISTRY[name]
        assert set(wf.enhance_keys()) == {
            "enhance", "upscale_model", "enhance_scale", "enhance_steps", "enhance_denoise",
        }, name
    # Flux keeps upscale_model in its recipe: with the toggle OFF that same
    # param drives the plain 4x upscale this workflow is named for, so it is a
    # real difference between two of its renders.
    assert set(WORKFLOW_REGISTRY["flux_t2i_upscaled"].enhance_keys()) == {
        "enhance", "enhance_scale", "enhance_steps", "enhance_denoise",
    }
    # A workflow with no tail at all declares nothing.
    assert WORKFLOW_REGISTRY["wan22_i2v"].enhance_keys() == ()


# ---- WAN 2.2 FLF2V Loop ----

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
    # Output size is derived from the input image, so it isn't a stored param.
    assert "width" not in params and "height" not in params


def test_i2v_workflows_have_no_manual_width_height_controls():
    # Every input_image-taking workflow derives its output size from that image
    # (in-graph for the 2.2 pair, app-side for ATI), so none exposes a manual
    # width/height control. Asserted across the whole registry, not just the 2.2
    # pair, so a new i2v can't silently regress to hardcoded dimensions.
    i2v_workflows = [
        wf for wf in WORKFLOW_REGISTRY.values() if "input_image" in wf.default_params()
    ]
    assert len(i2v_workflows) >= 3               # the 2.2 pair + ATI, at least
    for wf in i2v_workflows:
        keys = [d.key for d in wf.param_definitions()]
        assert "width" not in keys and "height" not in keys, wf.name
        params = wf.default_params()
        assert "width" not in params and "height" not in params, wf.name


def test_every_input_image_workflow_derives_its_size():
    # The size-derivation flag and the input-image param travel together: every
    # i2v workflow derives its output size from the image (so the form shows it
    # locked), and no manual-size workflow claims to.
    for wf in WORKFLOW_REGISTRY.values():
        takes_image = "input_image" in wf.default_params()
        assert wf.derives_size_from_input == takes_image, wf.name


def test_derived_display_size_measures_the_input_image(tmp_path, monkeypatch):
    # The form reads the derived width/height to show from here: the picked image
    # measured and scaled exactly as the run will size it.
    import origenerator.workflows.derived_size as ds
    from origenerator.workflows.derived_size import scale_to_total_pixels

    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "wide.png", (1920, 1080))

    for name in ("wan22_i2v", "wan22_flf2v_loop", "wan21_ati_i2v"):
        wf = WORKFLOW_REGISTRY[name]
        params = dict(wf.default_params(), input_image="wide.png")
        assert wf.derived_display_size(params) == scale_to_total_pixels(1920, 1080), name


def test_derived_display_size_is_none_when_not_derived_or_unmeasurable():
    # A manual-size workflow reports no derived size; a deriving one with no
    # measurable image reports None too, so the form shows nothing until an image
    # resolves rather than a misleading guess.
    manual = WORKFLOW_REGISTRY["sdxl_t2i"]
    assert manual.derives_size_from_input is False
    assert manual.derived_display_size(manual.default_params()) is None

    i2v = WORKFLOW_REGISTRY["wan22_i2v"]
    assert i2v.derived_display_size(dict(i2v.default_params(), input_image="")) is None
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
    # Node 9 is positive prompt
    assert payload["9"]["class_type"] == "CLIPTextEncode"
    assert payload["9"]["inputs"]["text"] == "video prompt"
    # Node 11 is LoadImage
    assert payload["11"]["class_type"] == "LoadImage"
    assert payload["11"]["inputs"]["image"] == "test.png"
    # Node 13 is KSamplerAdvanced (stage 1) - uses noise_seed
    assert payload["13"]["class_type"] == "KSamplerAdvanced"
    assert payload["13"]["inputs"]["noise_seed"] == 42
    # Node 14 is KSamplerAdvanced (stage 2) - uses seed
    assert payload["14"]["inputs"]["noise_seed"] == 99
    # Node 16 is VHS_VideoCombine
    assert payload["16"]["class_type"] == "VHS_VideoCombine"
    # Node 12 (WanFirstLastFrameToVideo) takes its size from the derive nodes:
    # LoadImage -> ImageScaleToTotalPixels -> GetImageSize -> width/height.
    scale_id = _node_id(payload, "ImageScaleToTotalPixels")
    getsize_id = _node_id(payload, "GetImageSize")
    assert payload[scale_id]["inputs"]["image"] == ["11", 0]
    assert payload[scale_id]["inputs"]["resolution_steps"] == 16
    assert payload[getsize_id]["inputs"]["image"] == [scale_id, 0]
    assert payload["12"]["inputs"]["width"] == [getsize_id, 0]
    assert payload["12"]["inputs"]["height"] == [getsize_id, 1]
    assert payload["12"]["inputs"]["length"] == params["frame_count"]


def test_wan22_i2v_size_override_replaces_the_in_graph_derivation():
    # Unlocking the derived size and setting an explicit WxH swaps the in-graph
    # ImageScaleToTotalPixels/GetImageSize derivation for a plain ImageScale to
    # that exact size, whose scaled image and literal width/height drive the video.
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
    assert video["width"] == 1024 and video["height"] == 576


def test_wan22_flf2v_size_override_replaces_the_in_graph_derivation():
    wf = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    params = dict(wf.default_params(), input_image="x.png", width=848, height=480)
    payload = wf.build_api_payload(params)

    assert _find_node(payload, "ImageScaleToTotalPixels") is None
    scale_id = _node_id(payload, "ImageScale")
    frame = payload["12"]["inputs"]
    # Both loop endpoints read the one explicitly scaled image.
    assert frame["start_image"] == [scale_id, 0]
    assert frame["end_image"] == [scale_id, 0]
    assert frame["width"] == 848 and frame["height"] == 480


def test_wan21_ati_i2v_honors_an_unlocked_size_override():
    # An explicit WxH wins over the input image's derived size, and the stroke is
    # rescaled into the overridden space — so an unlock overrides derivation even
    # when the (here nonexistent) image would otherwise be measured or fall back.
    from origenerator.workflows.wan21_ati_i2v import REFERENCE_HEIGHT, REFERENCE_WIDTH

    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    params = dict(wf.default_params(), input_image="whatever.png", width=720, height=480)
    track = _find_node(wf.build_api_payload(params), "WanTrackToVideo")

    assert track["inputs"]["width"] == 720
    assert track["inputs"]["height"] == 480
    sx, sy = 720 / REFERENCE_WIDTH, 480 / REFERENCE_HEIGHT
    anchor = json.loads(track["inputs"]["tracks"])[3][0]
    assert anchor == pytest.approx(
        {"x": params["anchor_x"] * sx, "y": params["anchor_y"] * sy}
    )


def test_wan22_flf2v_payload_generates_synced_foley_audio():
    # The loop workflow gets the same HunyuanVideo-Foley pass as the one-shot
    # i2v, but its writer is VHS_VideoCombine, so the audio rides its ``audio``
    # input. (The track won't loop seamlessly the way the frames do — players
    # restart it each cycle — but the clip itself is scored to its motion.)
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
    # HunyuanFoley rejects sub-second durations, so a clip shorter than 1s (the
    # default 21-frame loop at 16fps is 1.3s, but 5 frames is 0.2s) asks for a
    # clamped 1s of audio; the mux just carries the sliver of overhang.
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


# ---- WAN 2.2 I2V (dual-noise image-to-video) ----

def test_wan22_i2v_default_params_has_required_keys():
    wf = Wan22I2vWorkflow()
    params = wf.default_params()
    required = {
        "positive_prompt", "negative_prompt", "input_image",
        "noise_seed", "seed",
        "frame_count", "frame_rate",
        "steps", "cfg", "shift_high", "shift_low",
        "lora_strength_high", "lora_strength_low",
    }
    assert required.issubset(params.keys())
    assert "width" not in params and "height" not in params


def test_wan22_i2v_param_definitions_returns_paramdefs():
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

    # Image-to-video conditioning (NOT first-last-frame)
    i2v = _find_node(payload, "WanImageToVideo")
    assert i2v is not None
    assert i2v["inputs"]["length"] == params["frame_count"]
    assert _find_node(payload, "WanFirstLastFrameToVideo") is None

    # Size is derived in-graph from the loaded image, nothing hardcoded:
    # LoadImage -> ImageScaleToTotalPixels (/16, budget) -> GetImageSize -> w/h.
    load_id = _node_id(payload, "LoadImage")
    scale_id = _node_id(payload, "ImageScaleToTotalPixels")
    getsize_id = _node_id(payload, "GetImageSize")
    assert payload[scale_id]["inputs"]["image"] == [load_id, 0]
    assert payload[scale_id]["inputs"]["resolution_steps"] == 16
    assert payload[getsize_id]["inputs"]["image"] == [scale_id, 0]
    assert i2v["inputs"]["width"] == [getsize_id, 0]
    assert i2v["inputs"]["height"] == [getsize_id, 1]
    assert i2v["inputs"]["start_image"] == [scale_id, 0]  # the correctly-sized frame
    assert "width" not in params and "height" not in params

    # LoadImage feeds the start image
    assert payload[load_id]["inputs"]["image"] == "start.png"

    # CLIP-vision encode is present (i2v conditions on the image embedding)
    assert _find_node(payload, "CLIPVisionEncode") is not None

    # Two KSamplerAdvanced passes (high/low noise), split at steps // 2
    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    assert len(samplers) == 2
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["noise_seed"] == 842719365028413
    assert high["inputs"]["end_at_step"] == params["steps"] // 2
    assert low["inputs"]["start_at_step"] == params["steps"] // 2

    # Positive prompt is encoded
    assert any(
        n["class_type"] == "CLIPTextEncode" and n["inputs"]["text"] == "video prompt"
        for n in payload.values()
    )

    # Native video output nodes (CreateVideo + SaveVideo), not VHS
    assert _find_node(payload, "CreateVideo") is not None
    assert _find_node(payload, "SaveVideo") is not None
    assert _find_node(payload, "VHS_VideoCombine") is None


def test_wan22_i2v_split_step_and_per_stage_cfg_override_the_shared_values():
    # A LoRA author's recommended settings can be per-stage (e.g. 24 steps split
    # at 3, cfg 3.5 high / 6.0 low). split_step moves the handoff; cfg_high/
    # cfg_low replace the shared cfg for their sampler only.
    wf = Wan22I2vWorkflow()
    params = dict(wf.default_params(), steps=24, split_step=3,
                  cfg=3.5, cfg_high=2.0, cfg_low=6.0)
    payload = wf.build_api_payload(params)

    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["end_at_step"] == 3
    assert low["inputs"]["start_at_step"] == 3
    assert high["inputs"]["cfg"] == 2.0
    assert low["inputs"]["cfg"] == 6.0


def test_wan22_i2v_zero_split_and_cfg_overrides_keep_the_shared_behavior():
    # The 0 sentinels — the defaults — reproduce the classic graph: a steps//2
    # handoff and one cfg for both stages, so every stored recipe re-runs as it
    # originally ran.
    wf = Wan22I2vWorkflow()
    params = dict(wf.default_params(), steps=20, cfg=1.0)
    payload = wf.build_api_payload(params)

    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["end_at_step"] == 10
    assert low["inputs"]["start_at_step"] == 10
    assert high["inputs"]["cfg"] == 1.0
    assert low["inputs"]["cfg"] == 1.0


def test_wan22_i2v_payload_generates_synced_foley_audio():
    # Every i2v render carries a HunyuanVideo-Foley pass: the decoded frames
    # drive the foley sampler (so the audio follows the on-screen motion), and
    # its output is muxed into the file by CreateVideo's audio input. The
    # sampler's duration must equal the video's, derived from the same
    # frame_count/frame_rate the video nodes use, or the tracks drift.
    wf = Wan22I2vWorkflow()
    params = dict(
        wf.default_params(),
        audio_prompt="rhythmic audio",
        audio_negative_prompt="music",
        audio_seed=7,
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

    # The foley model and its deps are loaded from the params' file names, so a
    # generation records exactly which audio model scored it.
    model_id = _node_id(payload, "HunyuanModelLoader")
    deps_id = _node_id(payload, "HunyuanDependenciesLoader")
    assert sampler["hunyuan_model"] == [model_id, 0]
    assert sampler["hunyuan_deps"] == [deps_id, 0]
    assert payload[model_id]["inputs"]["model_name"] == params["foley_model"]
    assert payload[deps_id]["inputs"]["vae_name"] == params["foley_vae"]
    assert payload[deps_id]["inputs"]["synchformer_name"] == params["foley_synchformer"]

    # Slot 0 is audio_first — the single generated track — and CreateVideo
    # muxes it, so the SaveVideo output is a video WITH sound.
    create = _find_node(payload, "CreateVideo")
    assert create["inputs"]["audio"] == [sampler_id, 0]


def test_wan22_i2v_extract_output_info_uses_images_key():
    wf = Wan22I2vWorkflow()
    # ComfyUI's native SaveVideo reports outputs under "images", not "gifs"
    history = {
        "outputs": {
            "19": {
                "images": [
                    {"filename": "wan22_i2v_00001_.mp4", "subfolder": "video", "type": "output"}
                ],
                "animated": [True],
            }
        }
    }
    files = wf.extract_output_info(history)
    assert len(files) == 1
    assert files[0]["filename"] == "wan22_i2v_00001_.mp4"


# ---- WAN 2.1 ATI (stroke-tracked image-to-video) ----

def test_wan21_ati_i2v_payload_follows_an_authored_stroke_track():
    # The ATI workflow flips motion authorship: WanTrackToVideo conditions the
    # video on a stroke track built from the stroke params, so the pixels follow
    # the track instead of the track guessing at pixels. The track is ATI's
    # fixed 121-point/24fps convention: a 3-point cluster riding the authored
    # sine between stroke_top and stroke_bottom, plus one static point holding
    # the anchor (e.g. a anchor base) in place.
    from origenerator.workflows.wan21_ati_i2v import (
        REFERENCE_HEIGHT, REFERENCE_WIDTH, Wan21AtiI2vWorkflow,
    )

    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    assert wf.__class__ is Wan21AtiI2vWorkflow
    assert wf.output_type == "video"
    assert wf.looping is False
    assert wf.model_keys == ("unet",)

    params = dict(
        wf.default_params(),
        positive_prompt="slow steady stroking",
        input_image="start.png",
        seed=7,
        audio_seed=8,
        stroke_hz=1.0,
        stroke_x=200,
        stroke_top=400,
        stroke_bottom=600,
        anchor_x=180,
        anchor_y=700,
    )
    payload = wf.build_api_payload(params)

    track_node = _find_node(payload, "WanTrackToVideo")
    assert track_node is not None
    assert _find_node(payload, "WanImageToVideo") is None
    # "start.png" isn't a real file, so the size falls back to the reference
    # frame (scale 1.0), leaving the stroke coordinates below unscaled.
    assert track_node["inputs"]["width"] == REFERENCE_WIDTH
    assert track_node["inputs"]["height"] == REFERENCE_HEIGHT
    assert track_node["inputs"]["length"] == params["frame_count"]

    tracks = json.loads(track_node["inputs"]["tracks"])
    assert len(tracks) == 4                      # 3 stroke points + 1 static anchor
    assert all(len(t) == 121 for t in tracks)    # ATI's fixed track convention
    cluster = tracks[:3]
    ys = [pt["y"] for pt in cluster[1]]          # the centered stroke point
    assert ys[0] == pytest.approx(400, abs=1)    # starts at the top of the stroke
    assert min(ys) == pytest.approx(400, abs=2)  # tops ride near stroke_top...
    assert 575 <= max(ys) <= 601                 # ...bottoms near stroke_bottom
    anchor = tracks[3]
    assert all(pt == {"x": 180.0, "y": 700.0} for pt in anchor)  # pinned still

    # Two-stage sampling on the single ATI UNET (the high/low LoRA split; see
    # test_wan21_ati_i2v_offers_optional_high_and_low_noise_loras), seeded once.
    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    assert len(samplers) == 2
    assert all(n["inputs"]["noise_seed"] == 7 for n in samplers)
    assert _find_node(payload, "KSampler") is None
    unet = _find_node(payload, "UNETLoader")
    assert unet["inputs"]["unet_name"] == params["unet"]

    # The foley pass rides the decoded frames and CreateVideo muxes it, exactly
    # like the other video workflows.
    sampler_id = _node_id(payload, "HunyuanFoleySampler")
    decode_id = _node_id(payload, "VAEDecode")
    assert payload[sampler_id]["inputs"]["image"] == [decode_id, 0]
    assert payload[sampler_id]["inputs"]["seed"] == 8
    assert _find_node(payload, "CreateVideo")["inputs"]["audio"] == [sampler_id, 0]


def test_wan21_ati_i2v_authors_its_funscript_from_the_same_track():
    # The funscript is the track's own reversal points — the exact turnarounds
    # the pixel track eases between — mapped onto video time (the 121-point
    # track always spans 5.0s of track time stretched over the clip's real
    # duration) and normalized to stroke depth. Each top-of-stroke action must
    # land where the track's y actually crests. No pixel measurement anywhere.
    import json as _json

    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    params = dict(wf.default_params(), stroke_hz=1.2, frame_count=81, frame_rate=16.0, seed=42)
    actions = wf.authored_actions(params)
    payload = wf.build_api_payload(params)
    tracks = _json.loads(_find_node(payload, "WanTrackToVideo")["inputs"]["tracks"])
    ys = [pt["y"] for pt in tracks[1]]           # the centered cluster point
    top, bottom = params["stroke_top"], params["stroke_bottom"]
    depth = bottom - top

    assert actions[0] == {"at": 0, "pos": 100}   # the stroke starts at its top
    assert actions[-1]["at"] <= 81 / 16.0 * 1000
    assert all(0 <= a["pos"] <= 100 for a in actions)
    scale = (81 / 16.0) / 5.0
    pos = [a["pos"] for a in actions]
    crests = [
        i for i in range(1, len(actions) - 1)
        if pos[i] > pos[i - 1] and pos[i] >= pos[i + 1] and pos[i] >= 75
    ]
    assert crests, "the script must reach the top of the stroke repeatedly"
    for i in crests:                             # a top-of-stroke reversal
        s = round(actions[i]["at"] / 1000 / scale * 24)  # nearest track sample
        window = ys[max(0, s - 1):s + 2]
        assert min(window) <= top + 0.20 * depth  # the track crests there too

    # Workflows without an authored track say so with None, keeping the
    # metronome fallback for them.
    assert Wan22I2vWorkflow().authored_actions(Wan22I2vWorkflow().default_params()) is None


def test_wan21_ati_i2v_funscript_is_sparse_enough_for_the_osr2_driver():
    # The OSR2 driver re-sends "next action, time until it" on a 50ms poll, so
    # a dense script becomes a new target every tick and the device spasms
    # (user-reported: "unusably spastic... going to break my OSR2"). Actions
    # are reversals plus at most one shaping point per half-stroke, so every
    # gap stays far above the poll period at the default cadence.
    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    params = dict(wf.default_params(), seed=42)
    actions = wf.authored_actions(params)
    gaps = [b["at"] - a["at"] for a, b in zip(actions, actions[1:])]
    assert min(gaps) >= 120
    strokes = 1.2 * (81 / 16.0)                  # authored strokes in the clip
    assert len(actions) <= 2 * strokes * 2 + 2   # reversals + shaping, no more


def test_wan21_ati_i2v_stroke_decelerates_into_reversals_and_wobbles_like_a_hand():
    # Organic, not metronomic: each long-enough half-stroke carries a shaping
    # point at 55% time / 82% travel, so the device covers most of the distance
    # early and decelerates into the reversal; and the pacing wobbles per
    # half-stroke, seeded by the generation seed — deterministic per run,
    # re-rolled with it.
    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    params = dict(wf.default_params(), seed=42)
    actions = wf.authored_actions(params)
    assert actions == wf.authored_actions(dict(params))             # deterministic
    assert actions != wf.authored_actions(dict(params, seed=43))    # seed re-rolls it

    pos = [a["pos"] for a in actions]
    ats = [a["at"] for a in actions]
    reversal_idx = [
        i for i in range(1, len(pos) - 1)
        if (pos[i] - pos[i - 1]) * (pos[i + 1] - pos[i]) < 0
    ]
    assert reversal_idx, "the stroke must actually reverse"
    # Deceleration: between reversals, the leg INTO the reversal moves less
    # distance per millisecond than the leg leaving the previous one.
    decelerating = 0
    for i in reversal_idx:
        if i >= 2:
            speed_in = abs(pos[i] - pos[i - 1]) / max(1, ats[i] - ats[i - 1])
            speed_out = abs(pos[i - 1] - pos[i - 2]) / max(1, ats[i - 1] - ats[i - 2])
            if speed_in < speed_out:
                decelerating += 1
    assert decelerating >= len(reversal_idx) // 2

    # Human wobble: the spacing between successive top-of-stroke peaks varies.
    peaks = [ats[i] for i in reversal_idx if pos[i] > 75]
    gaps = {round((b - a) / 25) for a, b in zip(peaks, peaks[1:])}
    assert len(gaps) > 1


def test_wan21_ati_i2v_offers_optional_high_and_low_noise_loras(monkeypatch):
    # The LoRA ecosystem ships high/low-noise pairs, so the ATI workflow takes
    # one of each like the 2.2 workflows do — emulated on its single 2.1 base
    # by splitting the denoise into two KSamplerAdvanced stages at steps//2:
    # the high-noise LoRA patches the early-step model, the low-noise LoRA the
    # late-step one, both branching off the one UNET. Each slot is optional
    # ("None" omits its loader; that stage runs the base model unmodified).
    import origenerator.workflows.wan21_ati_i2v as ati_module
    from origenerator.workflows.model_files import NO_LORA
    from origenerator.workflows.wan21_ati_i2v import Wan21AtiI2vWorkflow

    options = [NO_LORA, "hand_high.safetensors", "hand_low.safetensors"]
    monkeypatch.setattr(ati_module, "list_lora_files", lambda fallback: options)

    wf = Wan21AtiI2vWorkflow()
    assert wf.lora_keys == ("lora_high", "lora_low")
    by_key = {pd.key: pd for pd in wf.param_definitions()}
    for level in ("high", "low"):
        picker = by_key[f"lora_{level}"]
        assert picker.type == "combo"
        assert picker.options == options
        assert picker.default == NO_LORA

    def lora_nodes(payload):
        return {nid: n for nid, n in payload.items()
                if n["class_type"] == "LoraLoaderModelOnly"}

    def stages(payload):
        samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
        assert _find_node(payload, "KSampler") is None
        assert len(samplers) == 2
        early = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
        late = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
        return early, late

    # Both bypassed: two stages, no LoRA loaders, both stages on the base model.
    params = dict(wf.default_params(), seed=5, steps=20)
    payload = wf.build_api_payload(params)
    early, late = stages(payload)
    assert lora_nodes(payload) == {}
    assert early["inputs"]["end_at_step"] == 10
    assert late["inputs"]["start_at_step"] == 10
    assert early["inputs"]["noise_seed"] == 5
    # Stage two refines stage one's latent.
    early_id = next(k for k, v in payload.items() if v is early)
    assert late["inputs"]["latent_image"] == [early_id, 0]

    # Both set: each stage's model chain runs its own LoRA off the shared UNET.
    payload = wf.build_api_payload(dict(
        params, lora_high="hand_high.safetensors", lora_strength_high=0.8,
        lora_low="hand_low.safetensors", lora_strength_low=0.6,
    ))
    early, late = stages(payload)
    loaders = lora_nodes(payload)
    assert len(loaders) == 2
    unet_id = _node_id(payload, "UNETLoader")

    def chain_lora(sampler):
        shift = payload[sampler["inputs"]["model"][0]]
        assert shift["class_type"] == "ModelSamplingSD3"
        loader = payload[shift["inputs"]["model"][0]]
        assert loader["class_type"] == "LoraLoaderModelOnly"
        assert loader["inputs"]["model"] == [unet_id, 0]
        return loader["inputs"]

    assert chain_lora(early)["lora_name"] == "hand_high.safetensors"
    assert chain_lora(early)["strength_model"] == 0.8
    assert chain_lora(late)["lora_name"] == "hand_low.safetensors"
    assert chain_lora(late)["strength_model"] == 0.6

    # One set, one bypassed: exactly one loader; the bypassed stage's shift
    # reads the UNET directly.
    payload = wf.build_api_payload(dict(params, lora_high="hand_high.safetensors"))
    early, late = stages(payload)
    assert len(lora_nodes(payload)) == 1
    late_shift = payload[late["inputs"]["model"][0]]
    assert late_shift["inputs"]["model"] == [unet_id, 0]


def _write_image(path, size):
    from PIL import Image

    Image.new("RGB", size, (128, 128, 128)).save(path)


def test_wan21_ati_i2v_derives_size_and_rescales_the_stroke(tmp_path, monkeypatch):
    # The output size is measured from the input image app-side (ATI can't derive
    # it in-graph), matching what ImageScaleToTotalPixels would produce, and the
    # stroke coordinates — authored in the 480×864 reference frame — are rescaled
    # into that derived space so the track lands in the same relative place
    # regardless of the image's aspect ratio.
    import origenerator.workflows.derived_size as ds
    from origenerator.workflows.derived_size import scale_to_total_pixels
    from origenerator.workflows.wan21_ati_i2v import (
        REFERENCE_HEIGHT, REFERENCE_WIDTH, Wan21AtiI2vWorkflow,
    )

    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "square.png", (1024, 1024))

    wf = Wan21AtiI2vWorkflow()
    params = dict(wf.default_params(), input_image="square.png")
    payload = wf.build_api_payload(params)

    derived_w, derived_h = scale_to_total_pixels(1024, 1024)
    assert (derived_w, derived_h) == (640, 640)
    track_node = _find_node(payload, "WanTrackToVideo")
    assert track_node["inputs"]["width"] == derived_w
    assert track_node["inputs"]["height"] == derived_h

    sx, sy = derived_w / REFERENCE_WIDTH, derived_h / REFERENCE_HEIGHT
    tracks = json.loads(track_node["inputs"]["tracks"])
    anchor = tracks[3]
    assert anchor[0] == pytest.approx(
        {"x": params["anchor_x"] * sx, "y": params["anchor_y"] * sy}
    )
    ys = [pt["y"] for pt in tracks[1]]                       # centered stroke point
    # The organic stroke starts exactly at the (scaled) top and lands within its
    # humanized shortfall of the (scaled) bottom — never beyond either bound.
    scaled_depth = (params["stroke_bottom"] - params["stroke_top"]) * sy
    assert min(ys) == pytest.approx(params["stroke_top"] * sy, abs=1)
    assert params["stroke_bottom"] * sy - 0.12 * scaled_depth <= max(ys)
    assert max(ys) <= params["stroke_bottom"] * sy + 1


def test_wan21_ati_i2v_falls_back_to_the_reference_size_when_unmeasurable(monkeypatch):
    # A missing or unset input image can't be measured, so the size falls back to
    # the 480×864 reference (scale 1.0 → the stroke coordinates pass through
    # unchanged) rather than crashing payload build.
    from origenerator.workflows.wan21_ati_i2v import (
        REFERENCE_HEIGHT, REFERENCE_WIDTH, Wan21AtiI2vWorkflow,
    )

    wf = Wan21AtiI2vWorkflow()
    for image in ("", "does_not_exist.png"):
        params = dict(wf.default_params(), input_image=image)
        track_node = _find_node(wf.build_api_payload(params), "WanTrackToVideo")
        assert track_node["inputs"]["width"] == REFERENCE_WIDTH
        assert track_node["inputs"]["height"] == REFERENCE_HEIGHT
        anchor = json.loads(track_node["inputs"]["tracks"])[3][0]
        assert anchor == {"x": float(params["anchor_x"]), "y": float(params["anchor_y"])}


def test_wan21_ati_stroke_coordinates_are_bounded_by_the_reference_frame():
    # The stroke coordinates are authored in the 480×864 reference frame (then
    # rescaled into the derived size), so their ranges are that frame's bounds —
    # X params to the reference width, Y params to the reference height — not the
    # old catch-all 4096. This keeps the form's meaning honest about the space.
    from origenerator.workflows.wan21_ati_i2v import REFERENCE_HEIGHT, REFERENCE_WIDTH

    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    by_key = {pd.key: pd for pd in wf.param_definitions()}
    for key in ("stroke_x", "anchor_x"):
        assert by_key[key].max_val == REFERENCE_WIDTH
    for key in ("stroke_top", "stroke_bottom", "anchor_y"):
        assert by_key[key].max_val == REFERENCE_HEIGHT


def test_wan21_ati_i2v_auto_aims_untouched_stroke_params(monkeypatch, tmp_path):
    # Choosing where in the frame a thing is doesn't scale, so when the stroke
    # coordinates are all still at their defaults, payload build detects the
    # anchor in the start frame and aims the track at it (converted into the
    # 480x864 reference frame, then scaled like any manual aim). Any edited
    # coordinate switches detection off entirely — the user's numbers win.
    # The funscript is unaffected either way: pos is normalized depth, so the
    # same seed yields the same actions no matter where the track points.
    import json as _json

    import origenerator.workflows.wan21_ati_i2v as ati
    from origenerator.workflows.wan21_ati_i2v import (
        REFERENCE_HEIGHT, REFERENCE_WIDTH, Wan21AtiI2vWorkflow,
    )

    aim = {"stroke_x": 0.5, "stroke_top": 0.25, "stroke_bottom": 0.5,
           "anchor_x": 0.45, "anchor_y": 0.6}
    calls = []
    monkeypatch.setattr(ati, "detect_grip_aim", lambda path: (calls.append(path), aim)[1])

    wf = Wan21AtiI2vWorkflow()
    params = dict(wf.default_params(), input_image="start.png", seed=9)
    payload = wf.build_api_payload(params)
    tracks = _json.loads(_find_node(payload, "WanTrackToVideo")["inputs"]["tracks"])
    # Missing image file -> reference-size fallback (scale 1.0), so the track
    # lands exactly at the detected fractions of the reference frame.
    assert tracks[1][0]["x"] == pytest.approx(round(0.5 * REFERENCE_WIDTH) + 3)  # cluster x-offset
    assert tracks[1][0]["y"] == pytest.approx(round(0.25 * REFERENCE_HEIGHT))    # starts at stroke top
    assert tracks[3][0] == {"x": float(round(0.45 * REFERENCE_WIDTH)),
                            "y": float(round(0.6 * REFERENCE_HEIGHT))}
    assert len(calls) == 1

    # The funscript ignores aim entirely: same seed, same actions, aimed or not.
    assert wf.authored_actions(params) == wf.authored_actions(
        dict(params, stroke_x=10, stroke_top=20, stroke_bottom=400, anchor_x=5, anchor_y=500)
    )

    # An edited coordinate is a manual override: no detection, the numbers rule.
    calls.clear()
    edited = dict(params, stroke_top=300)
    payload = wf.build_api_payload(edited)
    tracks = _json.loads(_find_node(payload, "WanTrackToVideo")["inputs"]["tracks"])
    assert calls == []
    assert tracks[1][0]["y"] == pytest.approx(300)


def test_wan21_ati_i2v_frame_count_avoids_the_resampler_crash():
    # ComfyUI's track resampler faults at exactly 121 frames (length-1=120 hits
    # its off-by-one), so the form's range stops at 113 on the same /4 stride
    # the other video workflows use.
    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    fc = next(pd for pd in wf.param_definitions() if pd.key == "frame_count")
    assert fc.default == 81
    assert fc.max_val == 113
    assert fc.min_val == 5
    assert fc.step == 4


# ---- SDXL Pose Transfer (re-skin an image, keeping its pose) ----

def test_sdxl_pose_transfer_is_registered_as_an_image_workflow():
    from origenerator.workflows.sdxl_pose_transfer import SdxlPoseTransferWorkflow

    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    assert wf.__class__ is SdxlPoseTransferWorkflow
    assert wf.name == "sdxl_pose_transfer"
    assert wf.output_type == "image"
    # The checkpoint identifies the output, exactly as in sdxl_t2i — the
    # controlnet is a conditioning aid, not what the gallery groups by.
    assert wf.model_keys == ("checkpoint",)
    assert wf.seed_keys() == ("seed",)
    # The output size follows the pose image's aspect ratio, so the workflow
    # derives it from the input rather than exposing manual width/height.
    assert wf.derives_size_from_input is True


def test_sdxl_pose_transfer_build_api_payload_structure():
    # The re-skin pipeline: the input image is scaled to the SDXL pixel budget
    # (keeping its aspect ratio), its structure is extracted — a DepthAnythingV2
    # map by default — and an SDXL ControlNet applies that map to both prompt
    # conditionings, while the sampler still denoises a fresh latent, sized off
    # the same derivation, so everything but the structure is up to the prompt
    # and checkpoint.
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(
        wf.default_params(),
        positive_prompt="a figure in a sunlit atrium",
        negative_prompt="grainy",
        input_image="pose_source.png",
        seed=77,
        controlnet_strength=0.65,
        controlnet_end=0.9,
    )
    assert params["control_mode"] == "depth"  # the shipped default
    payload = wf.build_api_payload(params)

    # The size chain: LoadImage -> ImageScaleToTotalPixels (1 MP, /16 stride)
    # -> GetImageSize -> the latent's width/height. No hardcoded dimensions.
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

    # The structure chain: DepthAnythingV2 reads the scaled image (so the map
    # is drawn in the same aspect the latent uses), the union ControlNet is
    # switched to its depth head, and the map is applied across both
    # conditionings at the form's strength/end values.
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

    # Both prompts route through the ControlNet apply into the sampler, which
    # otherwise runs the plain sdxl_t2i recipe on the checkpoint's model.
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
    assert sampler["inputs"]["denoise"] == params["denoise"]
    ckpt = _find_node(payload, "CheckpointLoaderSimple")
    assert ckpt["inputs"]["ckpt_name"] == params["checkpoint"]

    # Decoded through the standalone VAE like sdxl_t2i, then finished by the
    # enhance tail: the upscaler reads this decode, and SaveImage stores the
    # tail's own re-sampled decode (the chain itself is pinned by
    # test_sdxl_workflows_end_with_an_upscale_enhance_pass).
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
    # Unlocking the derived size swaps the budget-scaling for a plain ImageScale
    # to the explicit WxH, whose literal size drives the latent — and the pose
    # skeleton is still drawn from that same scaled image, so it keeps matching
    # the canvas it will be applied to.
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


def test_sdxl_pose_transfer_derived_display_size_uses_the_sdxl_budget(tmp_path, monkeypatch):
    # The form's locked Dimensions field must show the size this workflow will
    # actually render — the pose image's aspect at the 1 MP SDXL budget, not the
    # video workflows' 0.4 MP.
    import origenerator.workflows.derived_size as ds
    from origenerator.workflows.derived_size import scale_to_total_pixels

    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "tall.png", (1080, 1920))

    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(wf.default_params(), input_image="tall.png")
    derived = wf.derived_display_size(params)
    assert derived == scale_to_total_pixels(1080, 1920, megapixels=1.0)
    width, height = derived
    # Sanity-pin the budget itself: the derived area sits at ~1 MP, far above
    # what the 0.4 MP video budget would produce for the same image.
    assert 0.9 * 1024 * 1024 <= width * height <= 1.1 * 1024 * 1024


def test_sdxl_pose_transfer_pose_mode_swaps_depth_for_a_dwpose_skeleton():
    # "pose" mode is the single-standing-figure alternative: DWPose replaces
    # the depth chain (skeleton from the same scaled image, so it shares the
    # latent's aspect), and the union ControlNet switches to its openpose head.
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
    # xinsir's SDXL pose ControlNets were trained on thicker skeleton sticks
    # than the OpenPose standard, and comfyui_controlnet_aux ships a DWPose
    # toggle for exactly that. It follows the picked ControlNet by filename
    # (both shipped defaults are xinsir models), so swapping in a non-xinsir
    # ControlNet gets standard sticks without a second setting to keep in sync.
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    params = dict(wf.default_params(), input_image="x.png", control_mode="pose")
    assert "xinsir" in params["controlnet"].lower()  # the shipped default

    pose = _find_node(wf.build_api_payload(params), "DWPreprocessor")
    assert pose["inputs"]["scale_stick_for_xinsr_cn"] == "enable"

    other = dict(params, controlnet="OpenPoseXL2.safetensors")
    pose = _find_node(wf.build_api_payload(other), "DWPreprocessor")
    assert pose["inputs"]["scale_stick_for_xinsr_cn"] == "disable"


def test_sdxl_pose_transfer_union_type_node_only_wraps_union_controlnets():
    # SetUnionControlNetType tells a union model which head to run, but a
    # plain single-purpose ControlNet crashes on the extra argument — so the
    # node is added only when the picked file says it's a union model, and a
    # plain ControlNet is applied directly.
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


def test_sdxl_pose_transfer_extract_output_info():
    wf = WORKFLOW_REGISTRY["sdxl_pose_transfer"]
    save_id = next(
        nid for nid, node in wf.build_api_payload(wf.default_params()).items()
        if node["class_type"] == "SaveImage"
    )
    assert wf.output_node_id == save_id  # /history is read off the save node
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


# ---- WAN 2.2 T2I (dual-noise text-to-image) ----

def test_wan22_t2i_is_registered_as_an_image_workflow():
    assert WORKFLOW_REGISTRY["wan22_t2i"].__class__ is Wan22T2iWorkflow
    wf = Wan22T2iWorkflow()
    assert wf.name == "wan22_t2i"
    assert wf.output_type == "image"
    # Two diffusion models (high/low noise) identify the output, like the video
    # Wan workflows; a variation re-rolls both stage seeds.
    assert wf.model_keys == ("unet_high", "unet_low")
    assert wf.seed_keys() == ("noise_seed", "seed")


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

    def src(ref):  # resolve a [node_id, slot] link to its source node
        return payload[ref[0]]

    # A bare video latent is the canvas — text-to-image, so no input image and
    # none of the video conditioning the i2v/flf2v workflows use.
    latent = _find_node(payload, "EmptyHunyuanLatentVideo")
    assert latent["inputs"]["width"] == params["width"]
    assert latent["inputs"]["height"] == params["height"]
    assert _find_node(payload, "WanImageToVideo") is None
    assert _find_node(payload, "WanFirstLastFrameToVideo") is None
    assert _find_node(payload, "LoadImage") is None
    assert _find_node(payload, "CLIPVisionEncode") is None

    # Two KSamplerAdvanced passes split at steps // 2; stage 1 adds noise and
    # uses noise_seed, stage 2 refines from it and uses seed.
    samplers = [n for n in payload.values() if n["class_type"] == "KSamplerAdvanced"]
    assert len(samplers) == 2
    high = next(n for n in samplers if n["inputs"]["add_noise"] == "enable")
    low = next(n for n in samplers if n["inputs"]["add_noise"] == "disable")
    assert high["inputs"]["noise_seed"] == 42
    assert high["inputs"]["end_at_step"] == params["steps"] // 2
    assert low["inputs"]["noise_seed"] == 99
    assert low["inputs"]["start_at_step"] == params["steps"] // 2
    # Stage 2 refines stage 1's latent, not the empty one.
    high_id = next(k for k, v in payload.items() if v is high)
    assert low["inputs"]["latent_image"] == [high_id, 0]

    # Stage 1 runs the high-noise model, stage 2 the low-noise model — each via
    # its own ModelSamplingSD3 shift. Getting this backwards ruins the output.
    high_unet = src(src(high["inputs"]["model"])["inputs"]["model"])
    low_unet = src(src(low["inputs"]["model"])["inputs"]["model"])
    assert high_unet["inputs"]["unet_name"] == params["unet_high"]
    assert low_unet["inputs"]["unet_name"] == params["unet_low"]

    # One frame is pulled from the batch and saved as a still, not a video.
    assert _find_node(payload, "ImageFromBatch") is not None
    save = _find_node(payload, "SaveImage")
    assert save["inputs"]["filename_prefix"] == params["filename_prefix"]
    assert _find_node(payload, "SaveVideo") is None
    assert _find_node(payload, "VHS_VideoCombine") is None

    # The positive prompt is encoded and feeds both samplers.
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


# ---- Flux text-to-image, GGUF UNET, with a RealESRGAN upscale pass ----

def test_flux_t2i_upscaled_is_registered_as_an_image_workflow():
    assert WORKFLOW_REGISTRY["flux_t2i_upscaled"].__class__ is FluxT2iUpscaledWorkflow
    wf = FluxT2iUpscaledWorkflow()
    assert wf.name == "flux_t2i_upscaled"
    assert wf.output_type == "image"
    # The GGUF diffusion model identifies the output; the gallery groups by it,
    # so runs that differ only in which Flux model made them split into folders.
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
    # Flux is a guidance-distilled model: it samples at cfg 1.0 with an empty
    # negative, so the real "prompt strength" knob is FluxGuidance, not cfg.
    assert params["guidance"] == 4.5
    assert params["unet"].endswith(".gguf")


def test_flux_t2i_upscaled_exposes_a_gguf_model_picker(monkeypatch):
    # The GGUF diffusion model is a combo drawn from the installed diffusion
    # models, like SDXL's checkpoint picker — the one thing a user varies most.
    import origenerator.workflows.flux_t2i_upscaled as flux

    installed = ["a_flux.gguf", "b_flux.gguf"]
    monkeypatch.setattr(flux, "list_model_files", lambda category, fallback: installed)

    wf = FluxT2iUpscaledWorkflow()
    by_key = {pd.key: pd for pd in wf.param_definitions()}
    assert "unet" in by_key
    picker = by_key["unet"]
    assert picker.type == "combo"
    assert picker.options == installed
    assert picker.default == wf.default_params()["unet"]


def test_flux_t2i_upscaled_build_api_payload_structure():
    wf = FluxT2iUpscaledWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "a portrait"
    params["seed"] = 355448440510534
    params["guidance"] = 3.5
    payload = wf.build_api_payload(params)

    # GGUF UNET loader carries the model that identifies the run.
    unet = _find_node(payload, "UnetLoaderGGUF")
    assert unet["inputs"]["unet_name"] == params["unet"]

    # Flux's dual text encoders (clip_l + t5xxl) via DualCLIPLoader, type "flux".
    dual = _find_node(payload, "DualCLIPLoader")
    assert dual["inputs"]["type"] == "flux"
    assert dual["inputs"]["clip_name1"] == params["clip_name1"]
    assert dual["inputs"]["clip_name2"] == params["clip_name2"]

    # Guidance rides on the positive conditioning; the KSampler runs at cfg 1.0.
    fg = _find_node(payload, "FluxGuidance")
    assert fg["inputs"]["guidance"] == 3.5
    fg_id = _node_id(payload, "FluxGuidance")
    ks = _find_node(payload, "KSampler")
    assert ks["inputs"]["seed"] == 355448440510534
    assert ks["inputs"]["cfg"] == 1.0
    assert ks["inputs"]["positive"] == [fg_id, 0]

    # The saved image is the upscaled one: SaveImage reads the upscaler's output,
    # which in turn reads the VAE-decoded sample.
    upscale = _find_node(payload, "ImageUpscaleWithModel")
    decode_id = _node_id(payload, "VAEDecode")
    assert upscale["inputs"]["image"] == [decode_id, 0]
    upscale_id = _node_id(payload, "ImageUpscaleWithModel")
    save = _find_node(payload, "SaveImage")
    assert save["inputs"]["images"] == [upscale_id, 0]
    assert save["inputs"]["filename_prefix"] == params["filename_prefix"]
    assert _find_node(payload, "UpscaleModelLoader")["inputs"]["model_name"] == params["upscale_model"]

    # No LLM prompt-enhancer node: it hangs off the side of the saved graph,
    # unconnected, and needs a custom node + API key we don't drive.
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
