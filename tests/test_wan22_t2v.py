from __future__ import annotations

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.video_writer import VIDEO_WRITER
from origenerator.workflows.wan22_t2v import Wan22T2vWorkflow


def _payload(**changes) -> dict:
    workflow = Wan22T2vWorkflow()
    return workflow.build_api_payload({**workflow.default_params(), "positive_prompt": "a woman waves",
                                       **changes})


def _all(payload: dict, class_type: str) -> list[tuple[str, dict]]:
    return [(node_id, node) for node_id, node in payload.items() if node["class_type"] == class_type]


def test_the_form_is_offered_among_the_video_forms():
    assert isinstance(WORKFLOW_REGISTRY["wan22_t2v"], Wan22T2vWorkflow)


def test_a_video_is_made_from_the_prompt_alone_at_the_size_asked_for():
    payload = _payload(width=480, height=832, frame_count=81)
    ((_, latent),) = _all(payload, "EmptyHunyuanLatentVideo")
    assert latent["inputs"] == {"width": 480, "height": 832, "length": 81, "batch_size": 1}
    assert _all(payload, "LoadImage") == []
    assert _all(payload, "WanImageToVideo") == []


def test_the_first_pass_adds_the_noise_with_the_high_model_and_the_second_finishes_with_the_low():
    payload = _payload(steps=20, split_step=8)
    high, low = (node for _, node in _all(payload, "KSamplerAdvanced"))
    assert (high["inputs"]["add_noise"], high["inputs"]["end_at_step"]) == ("enable", 8)
    assert (low["inputs"]["add_noise"], low["inputs"]["start_at_step"]) == ("disable", 8)
    loaders = {node["inputs"]["unet_name"] for _, node in _all(payload, "UNETLoader")}
    assert loaders == {"wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
                       "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"}


def test_a_picked_lora_steers_its_own_pass():
    payload = _payload(lora_high="example_high.safetensors", lora_strength_high=0.8,
                       lora_low="example_low.safetensors")
    loras = {node["inputs"]["lora_name"]: node for _, node in _all(payload, "LoraLoaderModelOnly")}
    assert set(loras) == {"example_high.safetensors", "example_low.safetensors"}
    assert loras["example_high.safetensors"]["inputs"]["strength_model"] == 0.8


def test_its_model_rows_offer_the_models_that_make_video_from_text(installed_models):
    installed_models.add("diffusion_models", "example_t2v_high.safetensors", arch="wan_t2v")
    installed_models.add("diffusion_models", "example_i2v_high.safetensors", arch="wan")

    rows = {pd.key: pd for pd in Wan22T2vWorkflow().param_definitions()}

    assert "example_t2v_high.safetensors" in rows["unet_high"].options
    assert "example_i2v_high.safetensors" not in rows["unet_high"].options


def test_its_lora_rows_offer_a_lora_made_for_text_to_video(installed_models, recorded_base_models):
    installed_models.add("loras", "example_t2v_look.safetensors", arch="wan", lora=True)
    recorded_base_models({"example_t2v_look": "Wan Video 2.2 T2V-A14B"})

    rows = {pd.key: pd for pd in Wan22T2vWorkflow().param_definitions()}

    assert "example_t2v_look.safetensors" in rows["lora_high"].options


def test_a_video_longer_than_one_clip_goes_on_from_its_last_frame_with_the_image_to_video_models():
    payload = _payload(frame_count=241)
    ((_, latent),) = _all(payload, "EmptyHunyuanLatentVideo")
    continued = _all(payload, "WanImageToVideo")
    assert latent["inputs"]["length"] == 161
    assert [node["inputs"]["length"] for _, node in continued] == [81]
    start = payload[continued[0][1]["inputs"]["start_image"][0]]
    assert (start["class_type"], start["inputs"]["batch_index"]) == ("ImageFromBatch", 160)
    loaders = {node["inputs"]["unet_name"] for _, node in _all(payload, "UNETLoader")}
    assert "wan2.2_i2v_high_noise_14B_fp16.safetensors" in str(loaders)


def test_with_audio_on_the_sound_is_made_for_the_whole_video_and_written_with_it():
    payload = _payload(enable_audio=True, audio_prompt="waves on shingle")
    ((sampler_id, _),) = _all(payload, "HunyuanFoleySampler")
    ((_, writer),) = _all(payload, VIDEO_WRITER)
    assert writer["inputs"]["audio"][0] in payload
    assert sampler_id in payload


def test_its_lora_rows_leave_out_a_lora_made_for_image_to_video_which_the_i2v_form_offers(
        installed_models, recorded_base_models):
    installed_models.add("loras", "example_i2v_look.safetensors", arch="wan", lora=True)
    recorded_base_models({"example_i2v_look": "Wan Video 2.2 I2V-A14B"})

    t2v = {pd.key: pd for pd in Wan22T2vWorkflow().param_definitions()}
    i2v = {pd.key: pd for pd in WORKFLOW_REGISTRY["wan22_i2v"].param_definitions()}

    assert "example_i2v_look.safetensors" not in t2v["lora_high"].options
    assert "example_i2v_look.safetensors" in i2v["lora_high"].options
