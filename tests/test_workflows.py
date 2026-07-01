from PIL import Image

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef
from origenerator.workflows.image_to_video import ImageToVideoWorkflow, fit_dimensions
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow
from origenerator.workflows.wan22_t2i import Wan22T2iWorkflow


def _find_node(payload: dict, class_type: str) -> dict | None:
    for node in payload.values():
        if node.get("class_type") == class_type:
            return node
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


def test_workflows_expose_their_seed_param_keys():
    # A variation re-rolls exactly these; dual-noise video workflows have two.
    assert SdxlT2iWorkflow().seed_keys() == ("seed",)
    assert Wan22I2vWorkflow().seed_keys() == ("noise_seed", "seed")
    assert Wan22Flf2vLoopWorkflow().seed_keys() == ("noise_seed", "seed")


def test_finalize_params_is_a_noop_for_text_to_image_workflows(tmp_path):
    # Text-to-image workflows size the canvas from form values, so the base
    # finalize hook leaves their params (width/height included) untouched.
    wf = SdxlT2iWorkflow()
    params = wf.default_params()
    assert wf.finalize_params(params, tmp_path) == params


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


def test_i2v_workflows_derive_output_size_from_a_native_budget():
    # Both image-to-video workflows reshape the output to the input image at
    # their model's native pixel budget rather than a hardcoded resolution.
    i2v, flf2v = Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()
    assert isinstance(i2v, ImageToVideoWorkflow) and i2v.native_size == (720, 544)
    assert isinstance(flf2v, ImageToVideoWorkflow) and flf2v.native_size == (832, 480)


def test_i2v_workflows_have_no_manual_width_height_controls():
    for wf in (Wan22I2vWorkflow(), Wan22Flf2vLoopWorkflow()):
        keys = [d.key for d in wf.param_definitions()]
        assert "width" not in keys and "height" not in keys


def test_wan22_build_api_payload_structure():
    wf = Wan22Flf2vLoopWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "video prompt"
    params["negative_prompt"] = ""
    params["noise_seed"] = 42
    params["seed"] = 99
    params["input_image"] = "test.png"
    # finalize_params supplies width/height at build time; stand in for it here.
    params["width"], params["height"] = 848, 480
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
    # Node 12 is WanFirstLastFrameToVideo
    assert payload["12"]["inputs"]["width"] == params["width"]
    assert payload["12"]["inputs"]["length"] == params["frame_count"]


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


def test_wan22_i2v_finalizes_output_size_from_input_image(tmp_path):
    Image.new("RGB", (1920, 1080), (0, 0, 0)).save(tmp_path / "in.png")
    out = Wan22I2vWorkflow().finalize_params({"input_image": "in.png"}, tmp_path)
    assert (out["width"], out["height"]) == fit_dimensions(1920, 1080, 720 * 544)


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
    # finalize_params supplies width/height at build time; stand in for it here.
    params["width"], params["height"] = 720, 544
    payload = wf.build_api_payload(params)

    # Image-to-video conditioning (NOT first-last-frame)
    i2v = _find_node(payload, "WanImageToVideo")
    assert i2v is not None
    assert i2v["inputs"]["width"] == params["width"]
    assert i2v["inputs"]["length"] == params["frame_count"]
    assert _find_node(payload, "WanFirstLastFrameToVideo") is None

    # LoadImage feeds the start image
    assert _find_node(payload, "LoadImage")["inputs"]["image"] == "start.png"

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
