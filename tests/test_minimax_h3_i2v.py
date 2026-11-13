from __future__ import annotations

import pytest

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.minimax_h3_i2v import (
    H3_FPS,
    MiniMaxH3I2vWorkflow,
    frames_on_the_models_steps,
)
from origenerator.workflows.video_writer import VIDEO_WRITER


def _payload(**changes) -> dict:
    workflow = MiniMaxH3I2vWorkflow()
    return workflow.build_api_payload({**workflow.default_params(), "input_image": "start.png",
                                       "positive_prompt": "a woman waves", **changes})


def _only(payload: dict, class_type: str) -> tuple[str, dict]:
    (found,) = [(node_id, node) for node_id, node in payload.items()
                if node["class_type"] == class_type]
    return found


def test_the_form_is_offered_among_the_video_forms():
    assert isinstance(WORKFLOW_REGISTRY["minimax_h3_i2v"], MiniMaxH3I2vWorkflow)


@pytest.mark.parametrize(("asked", "made"), [(1, 5), (5, 5), (6, 22), (121, 124), (124, 124),
                                             (241, 243), (361, 362)])
def test_a_length_is_rounded_up_onto_the_seventeen_frame_steps_the_model_makes(asked, made):
    assert frames_on_the_models_steps(asked) == made


def test_the_start_image_is_the_first_frame_and_sets_the_size():
    payload = _payload()
    _, video = _only(payload, "MiniMaxH3ImageToVideo")
    load_id, load = _only(payload, "LoadImage")
    assert load["inputs"]["image"] == "start.png"
    scale_id, _ = _only(payload, "ImageScaleToTotalPixels")
    assert video["inputs"]["first_frame"] == [scale_id, 0]
    assert payload[scale_id]["inputs"]["image"] == [load_id, 0]
    assert payload[scale_id]["inputs"]["resolution_steps"] == 32
    assert video["inputs"]["prompt"] == "a woman waves"


def test_the_duration_picked_is_made_on_the_models_frame_steps():
    _, video = _only(_payload(frame_count=124), "MiniMaxH3ImageToVideo")
    assert video["inputs"]["length"] == 124


def test_a_video_longer_than_the_model_was_trained_on_is_made_in_clips_each_starting_on_the_last_frame():
    payload = _payload(frame_count=frames_on_the_models_steps(30 * 24))
    lengths = [node["inputs"]["length"] for node in payload.values()
               if node["class_type"] == "MiniMaxH3ImageToVideo"]
    assert all(length <= 362 and (length - 5) % 17 == 0 for length in lengths)
    assert lengths[0] + sum(length - 1 for length in lengths[1:]) >= 30 * 24
    second = payload["s1_h3"]["inputs"]["first_frame"]
    assert payload[second[0]]["class_type"] == "ImageFromBatch"
    assert payload[second[0]]["inputs"]["batch_index"] == lengths[0] - 1


def test_the_sound_of_each_clip_is_joined_in_order():
    payload = _payload(frame_count=frames_on_the_models_steps(30 * 24))
    _, writer = _only(payload, VIDEO_WRITER)
    last_join = payload[writer["inputs"]["audio"][0]]
    assert last_join["class_type"] == "AudioConcat"
    assert last_join["inputs"]["direction"] == "after"


def test_the_video_is_written_at_the_models_own_frame_rate_with_the_sound_it_made():
    payload = _payload()
    _, writer = _only(payload, VIDEO_WRITER)
    audio_id, _ = _only(payload, "VAEDecodeAudio")
    assert writer["inputs"]["frame_rate"] == H3_FPS
    assert writer["inputs"]["audio"] == [audio_id, 0]


def test_a_higher_frame_rate_fills_in_whole_multiples_of_the_models_own_rate():
    payload = _payload(frame_rate=50.0)
    rife_id, rife = _only(payload, "RIFE VFI")
    assert rife["inputs"]["multiplier"] == 2
    _, writer = _only(payload, VIDEO_WRITER)
    assert (writer["inputs"]["images"], writer["inputs"]["frame_rate"]) == ([rife_id, 0], 48.0)


def test_a_picked_lora_steers_the_model_that_samples():
    payload = _payload(lora="h3_look.safetensors", lora_strength=0.8)
    lora_id, lora = _only(payload, "LoraLoaderModelOnly")
    unet_id, _ = _only(payload, "UNETLoader")
    assert lora["inputs"] == {"model": [unet_id, 0], "lora_name": "h3_look.safetensors",
                              "strength_model": 0.8}
    _, guider = _only(payload, "BasicGuider")
    _, schedule = _only(payload, "BasicScheduler")
    assert guider["inputs"]["model"] == schedule["inputs"]["model"] == [lora_id, 0]


def test_the_seed_and_steps_reach_the_sampler():
    payload = _payload(noise_seed=42, steps=12)
    assert _only(payload, "RandomNoise")[1]["inputs"]["noise_seed"] == 42
    assert _only(payload, "BasicScheduler")[1]["inputs"]["steps"] == 12
