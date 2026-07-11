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


def test_wan22_i2v_payload_generates_synced_foley_audio():
    # Every i2v render carries a HunyuanVideo-Foley pass: the decoded frames
    # drive the foley sampler (so the audio follows the on-screen motion), and
    # its output is muxed into the file by CreateVideo's audio input. The
    # sampler's duration must equal the video's, derived from the same
    # frame_count/frame_rate the video nodes use, or the tracks drift.
    wf = Wan22I2vWorkflow()
    params = dict(
        wf.default_params(),
        audio_prompt="skin slapping, redacted",
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
    assert sampler["prompt"] == "skin slapping, redacted"
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
    # the anchor (e.g. a redacted base) in place.
    import json as _json

    from origenerator.workflows.wan21_ati_i2v import Wan21AtiI2vWorkflow

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
    assert track_node["inputs"]["width"] == params["width"]
    assert track_node["inputs"]["height"] == params["height"]
    assert track_node["inputs"]["length"] == params["frame_count"]

    tracks = _json.loads(track_node["inputs"]["tracks"])
    assert len(tracks) == 4                      # 3 stroke points + 1 static anchor
    assert all(len(t) == 121 for t in tracks)    # ATI's fixed track convention
    cluster = tracks[:3]
    ys = [pt["y"] for pt in cluster[1]]          # the centered stroke point
    assert min(ys) == pytest.approx(400, abs=1)  # reaches stroke_top...
    assert max(ys) == pytest.approx(600, abs=1)  # ...and stroke_bottom
    assert ys[0] == pytest.approx(400, abs=1)    # starts at the top of the stroke
    anchor = tracks[3]
    assert all(pt == {"x": 180.0, "y": 700.0} for pt in anchor)  # pinned still

    # Single-stage 2.1 sampling: one KSampler on the ATI UNET, no dual-noise pair.
    samplers = [n for n in payload.values() if n["class_type"] == "KSampler"]
    assert len(samplers) == 1
    assert samplers[0]["inputs"]["seed"] == 7
    assert _find_node(payload, "KSamplerAdvanced") is None
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
    # The funscript is the track: alternating extremes at the authored cadence,
    # starting at the top (the cluster's sine starts there), mapped onto video
    # time — the 121-point track always spans 5.0s of track time stretched over
    # the clip's real duration. No pixel measurement anywhere.
    wf = WORKFLOW_REGISTRY["wan21_ati_i2v"]
    params = dict(wf.default_params(), stroke_hz=1.2, frame_count=81, frame_rate=16.0)
    actions = wf.authored_actions(params)

    assert actions[0] == {"at": 0, "pos": 100}
    assert actions[1]["pos"] == 0
    scale = (81 / 16.0) / 5.0
    assert actions[1]["at"] == pytest.approx(0.5 / 1.2 * scale * 1000, abs=1)
    assert actions[-1]["at"] <= 81 / 16.0 * 1000
    positions = [a["pos"] for a in actions]
    assert positions == [100 if i % 2 == 0 else 0 for i in range(len(positions))]

    # Workflows without an authored track say so with None, keeping the
    # metronome fallback for them.
    assert Wan22I2vWorkflow().authored_actions(Wan22I2vWorkflow().default_params()) is None


def test_wan21_ati_i2v_offers_an_optional_lora(monkeypatch):
    # The 2.1 base carries none of the motion vocabulary the 2.2 NSFW LoRAs
    # taught, so the workflow exposes a LoRA slot for 2.1-compatible LoRAs —
    # optional exactly like the 2.2 workflows' slots: "None" omits the loader
    # node and the base model runs unmodified.
    import origenerator.workflows.wan21_ati_i2v as ati_module
    from origenerator.workflows.model_files import NO_LORA
    from origenerator.workflows.wan21_ati_i2v import Wan21AtiI2vWorkflow

    options = [NO_LORA, "hand.safetensors"]
    monkeypatch.setattr(ati_module, "list_lora_files", lambda fallback: options)

    wf = Wan21AtiI2vWorkflow()
    assert wf.lora_keys == ("lora",)
    picker = {pd.key: pd for pd in wf.param_definitions()}["lora"]
    assert picker.type == "combo"
    assert picker.options == options
    assert picker.default == NO_LORA

    def lora_nodes(payload):
        return [n for n in payload.values() if n["class_type"] == "LoraLoaderModelOnly"]

    bypassed = wf.build_api_payload(dict(wf.default_params(), lora=NO_LORA))
    assert lora_nodes(bypassed) == []

    params = dict(wf.default_params(), lora="hand.safetensors", lora_strength=0.8)
    payload = wf.build_api_payload(params)
    (loader,) = lora_nodes(payload)
    assert loader["inputs"]["lora_name"] == "hand.safetensors"
    assert loader["inputs"]["strength_model"] == 0.8
    # The shift node reads the LoRA'd model, so the sampler runs it.
    unet_id = _node_id(payload, "UNETLoader")
    lora_id = _node_id(payload, "LoraLoaderModelOnly")
    shift = _find_node(payload, "ModelSamplingSD3")
    assert loader["inputs"]["model"] == [unet_id, 0]
    assert shift["inputs"]["model"] == [lora_id, 0]


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
