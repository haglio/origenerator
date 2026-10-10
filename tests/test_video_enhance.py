"""The standalone video enhancer: each frame upscaled, then redrawn with more
detail by the video model's second-pass model, guided by the start picture."""
from __future__ import annotations

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.video_enhance import (
    VideoEnhanceWorkflow,
    refine_window_frames,
)


def test_video_enhance_is_registered_as_machinery_that_makes_videos():
    wf = WORKFLOW_REGISTRY["video_enhance"]
    assert wf.__class__ is VideoEnhanceWorkflow
    assert wf.output_type == "video"
    assert wf.selectable is False
    assert wf.model_keys == ("unet_low",)
    assert wf.lora_keys == ("lora_low",)
    assert wf.seed_keys() == ("seed",)


def _node_id(payload: dict, class_type: str) -> str:
    return next(node_id for node_id, node in payload.items() if node["class_type"] == class_type)


def _nodes(payload: dict, class_type: str) -> list[dict]:
    return [node for node in payload.values() if node["class_type"] == class_type]


def _enhance_params(**overrides) -> dict:
    params = dict(WORKFLOW_REGISTRY["video_enhance"].default_params(),
                  input_video="video/wan22_i2v_00007.mp4 [output]",
                  start_image="image/sdxl_t2i_00003_.png [output]", positive_prompt="warm window light",
                  negative_prompt="blurry", seed=5, enhance_steps=12, enhance_denoise=0.2,
                  cfg_low=2.5, lora_low="a_low_lora.safetensors", lora_strength_low=0.7)
    return {**params, **overrides}


def test_a_short_video_is_upscaled_encoded_and_redrawn_as_one_stretch_guided_by_its_start_picture():
    wf = WORKFLOW_REGISTRY["video_enhance"]
    payload = wf.build_api_payload(_enhance_params())

    load_id = _node_id(payload, "LoadVideo")
    assert payload[load_id]["inputs"]["file"] == "video/wan22_i2v_00007.mp4 [output]"
    parts_id = _node_id(payload, "GetVideoComponents")
    assert payload[parts_id]["inputs"]["video"] == [load_id, 0]
    # Played at the rate it was made at: every frame of the file is a frame the
    # model made, so none is picked out and none is filled in afterwards.
    assert not _nodes(payload, "VHS_SelectEveryNthImage") and not _nodes(payload, "RIFE VFI")

    upscale_id = _node_id(payload, "ImageUpscaleWithModel")
    assert payload[upscale_id]["inputs"]["image"] == [parts_id, 0]
    rescale_id = _node_id(payload, "ImageScaleBy")
    assert payload[rescale_id]["inputs"] == {"image": [upscale_id, 0], "upscale_method": "lanczos",
                                             "scale_by": 1.5 / 4}
    size_id = _node_id(payload, "GetImageSize")
    assert payload[size_id]["inputs"]["image"] == [rescale_id, 0]
    encode_id = _node_id(payload, "VAEEncode")
    assert payload[encode_id]["inputs"]["pixels"] == [rescale_id, 0]

    # The start picture, at the enhanced frame's own size, is what the model
    # is told the stretch starts on; the frames themselves are what it redraws.
    picture_id = _node_id(payload, "LoadImage")
    assert payload[picture_id]["inputs"]["image"] == "image/sdxl_t2i_00003_.png [output]"
    fitted = _node_id(payload, "ImageScale")
    assert payload[fitted]["inputs"] == {"image": [picture_id, 0], "upscale_method": "lanczos",
                                        "width": [size_id, 0], "height": [size_id, 1], "crop": "disabled"}
    [conditioning] = _nodes(payload, "WanImageToVideo")
    assert conditioning["inputs"]["start_image"] == [fitted, 0]
    assert conditioning["inputs"]["width"] == [size_id, 0]
    assert conditioning["inputs"]["height"] == [size_id, 1]
    assert conditioning["inputs"]["length"] == 81
    assert payload[_node_id(payload, "CLIPVisionEncode")]["inputs"]["image"] == [fitted, 0]

    [sampler] = _nodes(payload, "KSampler")
    assert sampler["inputs"]["latent_image"] == [encode_id, 0]
    assert sampler["inputs"]["denoise"] == 0.2
    assert sampler["inputs"]["steps"] == 12
    assert sampler["inputs"]["cfg"] == 2.5
    assert sampler["inputs"]["seed"] == 5
    shifted = payload[sampler["inputs"]["model"][0]]
    assert shifted["class_type"] == "ModelSamplingSD3" and shifted["inputs"]["shift"] == 8.0
    lora = payload[shifted["inputs"]["model"][0]]
    assert lora["class_type"] == "LoraLoaderModelOnly"
    assert lora["inputs"]["lora_name"] == "a_low_lora.safetensors"
    assert lora["inputs"]["strength_model"] == 0.7
    assert payload[lora["inputs"]["model"][0]]["inputs"]["unet_name"] == wf.default_params()["unet_low"]
    assert any(n["class_type"] == "CLIPTextEncode" and n["inputs"]["text"] == "warm window light"
               for n in payload.values())

    decode_id = _node_id(payload, "VAEDecode")
    assert payload[decode_id]["inputs"]["samples"] == [_node_id(payload, "KSampler"), 0]
    create_id = _node_id(payload, "CreateVideo")
    assert payload[create_id]["inputs"] == {"images": [decode_id, 0], "fps": 16.0, "audio": [parts_id, 1]}
    assert payload[wf.output_node_id]["class_type"] == "SaveVideo"
    assert payload[wf.output_node_id]["inputs"]["video"] == [create_id, 0]
    assert payload[wf.output_node_id]["inputs"]["filename_prefix"] == "video/video_enhance"


def test_a_video_played_faster_than_it_was_made_has_its_own_frames_picked_out_and_filled_in_again():
    wf = WORKFLOW_REGISTRY["video_enhance"]
    payload = wf.build_api_payload(_enhance_params(frame_rate=112.0))

    parts_id = _node_id(payload, "GetVideoComponents")
    picked_id = _node_id(payload, "VHS_SelectEveryNthImage")
    assert payload[picked_id]["inputs"] == {"images": [parts_id, 0], "select_every_nth": 7,
                                            "skip_first_images": 0}
    assert payload[_node_id(payload, "ImageUpscaleWithModel")]["inputs"]["image"] == [picked_id, 0]
    smooth_id = _node_id(payload, "RIFE VFI")
    assert payload[smooth_id]["inputs"]["frames"] == [_node_id(payload, "VAEDecode"), 0]
    assert payload[smooth_id]["inputs"]["multiplier"] == 7
    create = payload[_node_id(payload, "CreateVideo")]
    assert create["inputs"]["images"] == [smooth_id, 0]
    assert create["inputs"]["fps"] == 112.0


def test_a_long_video_is_redrawn_in_stretches_each_starting_on_its_own_first_frame():
    # 85 frames fit one redraw at 1.5x of a 480p frame; a 10-second video is
    # two stretches sharing a frame, the second told it starts on its own
    # first frame rather than on the start picture.
    assert refine_window_frames(0.4) == 85
    assert refine_window_frames(0.88) == 37
    wf = WORKFLOW_REGISTRY["video_enhance"]
    payload = wf.build_api_payload(_enhance_params(frame_count=161))

    cuts = _nodes(payload, "ImageFromBatch")
    stretches = [(n["inputs"]["batch_index"], n["inputs"]["length"]) for n in cuts
                 if n["inputs"]["image"] == [_node_id(payload, "GetVideoComponents"), 0]]
    assert stretches == [(0, 85), (84, 77)]
    first, second = _nodes(payload, "WanImageToVideo")
    assert first["inputs"]["length"] == 85
    assert first["inputs"]["start_image"] == [_node_id(payload, "ImageScale"), 0]
    assert second["inputs"]["length"] == 77
    own_first_frame = payload[second["inputs"]["start_image"][0]]
    assert own_first_frame["class_type"] == "ImageFromBatch"
    assert own_first_frame["inputs"]["batch_index"] == 0 and own_first_frame["inputs"]["length"] == 1
    seeds = [n["inputs"]["seed"] for n in _nodes(payload, "KSampler")]
    assert seeds == [5, 6]
    [join] = _nodes(payload, "ImageBatch")
    after_the_shared_frame = payload[join["inputs"]["image2"][0]]
    assert after_the_shared_frame["inputs"]["batch_index"] == 1
    assert after_the_shared_frame["inputs"]["length"] == 76
    assert payload[_node_id(payload, "CreateVideo")]["inputs"]["images"] == [_node_id(payload, "ImageBatch"), 0]


def test_a_video_with_no_start_picture_starts_on_its_own_first_frame():
    wf = WORKFLOW_REGISTRY["video_enhance"]
    payload = wf.build_api_payload(_enhance_params(start_image=""))

    assert not _nodes(payload, "LoadImage") and not _nodes(payload, "ImageScale")
    [conditioning] = _nodes(payload, "WanImageToVideo")
    own_first_frame = payload[conditioning["inputs"]["start_image"][0]]
    assert own_first_frame["class_type"] == "ImageFromBatch"
    assert own_first_frame["inputs"]["image"] == [_node_id(payload, "ImageScaleBy"), 0]
