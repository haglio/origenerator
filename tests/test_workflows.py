from origenerator.workflows.base import ParamDef
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow


def _find_node(payload: dict, class_type: str) -> dict | None:
    for node in payload.values():
        if node.get("class_type") == class_type:
            return node
    return None


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
        "width", "height", "frame_count", "frame_rate",
        "lora_strength_high", "lora_strength_low",
    }
    assert required.issubset(params.keys())


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
        "width", "height", "frame_count", "frame_rate",
        "steps", "cfg", "shift_high", "shift_low",
        "lora_strength_high", "lora_strength_low",
    }
    assert required.issubset(params.keys())


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
