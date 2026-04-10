from origenerator.workflows.base import ParamDef
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow


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
        "positive_prompt", "negative_prompt", "input_image", "seed",
        "width", "height", "frame_count", "frame_rate",
        "lora_strength_high", "lora_strength_low",
    }
    assert required.issubset(params.keys())


def test_wan22_build_api_payload_structure():
    wf = Wan22Flf2vLoopWorkflow()
    params = wf.default_params()
    params["positive_prompt"] = "video prompt"
    params["negative_prompt"] = ""
    params["seed"] = 99
    params["input_image"] = "test.png"
    payload = wf.build_api_payload(params)
    # Node 9 is positive prompt
    assert payload["9"]["class_type"] == "CLIPTextEncode"
    assert payload["9"]["inputs"]["text"] == "video prompt"
    # Node 11 is LoadImage
    assert payload["11"]["class_type"] == "LoadImage"
    assert payload["11"]["inputs"]["image"] == "test.png"
    # Node 13 is KSamplerAdvanced (stage 1)
    assert payload["13"]["class_type"] == "KSamplerAdvanced"
    assert payload["13"]["inputs"]["noise_seed"] == 99
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
