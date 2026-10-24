"""MiniMax H3 image-to-video: one model, one pass, the picture and its stereo
sound made together."""
from __future__ import annotations

from PIL import Image

import origenerator.workflows.derived_size as ds
from origenerator.comfy_graph import graph_model_params
from origenerator.importer import _workflow_from_nodes
from origenerator.progress import sampler_costs, stage_names
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.duration import frames_for_seconds, seconds_for_frames
from origenerator.workflows.frame_rate import NATIVE_FPS
from origenerator.workflows.minimax_h3_i2v import H3_FPS, MiniMaxH3I2vWorkflow
from origenerator.workflows.minimax_h3_ref2v import MiniMaxH3Ref2vWorkflow


def _node_id(payload: dict, class_type: str) -> str:
    found = [node_id for node_id, node in payload.items() if node["class_type"] == class_type]
    assert len(found) == 1, (class_type, found)
    return found[0]


def _payload(**overrides) -> tuple[MiniMaxH3I2vWorkflow, dict]:
    wf = MiniMaxH3I2vWorkflow()
    params = dict(wf.default_params(), input_image="start.png", seed=7, **overrides)
    return wf, wf.build_api_payload(params)


def test_h3_image_to_video_is_a_video_workflow_picked_beside_wans():
    wf = WORKFLOW_REGISTRY["minimax_h3_i2v"]
    assert isinstance(wf, MiniMaxH3I2vWorkflow)
    assert wf.selectable and wf.output_type == "video"
    assert wf.display_name == "MiniMax H3 Image-to-Video"
    # H3 paces its motion at 24 frames a second where WAN paces at 16, and
    # takes its canvas in multiples of 32 where WAN takes 16.
    assert wf.native_fps == H3_FPS == 24.0 != NATIVE_FPS
    assert wf.derives_size_from_input and wf.size_stride == 32


def test_the_graph_runs_h3_once_and_writes_its_own_sound_into_the_file():
    # Comfy's own H3 template, read into this app's shape: the model, its text
    # encoder and its two VAEs come off disk; the start image, prompt and
    # length go into the one H3 conditioning node; a single sampler pass
    # denoises picture and sound together; the video VAE decodes the frames
    # and the audio VAE the soundtrack, and the one video writer every video
    # here saves with muxes them at the rate H3 made them.
    wf, payload = _payload(positive_prompt="she laughs and waves", frame_count=124, steps=8)
    params = dict(wf.default_params(), input_image="start.png")

    unet = _node_id(payload, "UNETLoader")
    assert payload[unet]["inputs"]["unet_name"] == params["unet"]
    clip = _node_id(payload, "CLIPLoader")
    assert payload[clip]["inputs"] == {"clip_name": params["clip_name"], "type": "minimax",
                                       "device": "default"}
    vaes = {payload[n]["inputs"]["vae_name"]: n for n in payload
            if payload[n]["class_type"] == "VAELoader"}
    video_vae, audio_vae = vaes[params["vae_name"]], vaes[params["audio_vae_name"]]

    i2v = _node_id(payload, "MiniMaxH3ImageToVideo")
    conditioning = payload[i2v]["inputs"]
    assert conditioning["clip"] == [clip, 0] and conditioning["vae"] == [video_vae, 0]
    assert conditioning["prompt"] == "she laughs and waves"
    assert conditioning["length"] == 124
    assert conditioning["first_frame"] == [_node_id(payload, "ImageScaleToTotalPixels"), 0]
    size = _node_id(payload, "GetImageSize")
    assert (conditioning["width"], conditioning["height"]) == ([size, 0], [size, 1])
    assert "last_frame" not in conditioning

    sampler = payload[_node_id(payload, "SamplerCustomAdvanced")]["inputs"]
    assert payload[sampler["noise"][0]]["inputs"]["noise_seed"] == 7
    guider = payload[sampler["guider"][0]]
    assert guider["class_type"] == "BasicGuider"
    assert guider["inputs"]["conditioning"] == [i2v, 0]
    assert payload[sampler["sampler"][0]]["inputs"]["sampler_name"] == "res_multistep"
    schedule = payload[sampler["sigmas"][0]]["inputs"]
    assert (schedule["scheduler"], schedule["steps"], schedule["denoise"]) == ("simple", 8, 1.0)
    assert sampler["latent_image"] == [i2v, 1]

    sampled = [_node_id(payload, "SamplerCustomAdvanced"), 0]
    frames = _node_id(payload, "VAEDecode")
    assert payload[frames]["inputs"] == {"samples": sampled, "vae": [video_vae, 0]}
    sound = _node_id(payload, "VAEDecodeAudio")
    assert payload[sound]["inputs"] == {"samples": sampled, "vae": [audio_vae, 0]}

    writer = payload[wf.output_node_id]
    assert writer["class_type"] == "VHS_VideoCombine"
    assert writer["inputs"]["images"] == [frames, 0]
    assert writer["inputs"]["audio"] == [sound, 0]
    assert writer["inputs"]["frame_rate"] == 24.0
    assert writer["inputs"]["filename_prefix"] == "video/minimax_h3_i2v"

    # No pass scores the clip afterwards, nothing fills in frames between the
    # model's, and the prompt is read by the H3 node rather than a text encode.
    classes = {node["class_type"] for node in payload.values()}
    assert not classes & {"HunyuanFoleySampler", "RIFE VFI", "CLIPTextEncode", "KSampler"}


def test_the_canvas_is_the_start_image_at_the_video_budget_on_h3s_32_pixel_grid(tmp_path, monkeypatch):
    # The same 0.4 megapixel budget the WAN videos run at, with each side on a
    # multiple of 32 as H3 wants it: Comfy's template table gives 864 x 480 for
    # a widescreen source at that budget, and the size the form shows is the
    # size the graph derives.
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    Image.new("RGB", (1920, 1080)).save(tmp_path / "wide.png")
    wf = MiniMaxH3I2vWorkflow()

    assert wf.derived_display_size(dict(wf.default_params(), input_image="wide.png")) == (864, 480)

    payload = wf.build_api_payload(dict(wf.default_params(), input_image="wide.png"))
    scale = payload[_node_id(payload, "ImageScaleToTotalPixels")]["inputs"]
    assert (scale["megapixels"], scale["resolution_steps"]) == (0.4, 32)


def test_turbo_puts_the_speed_lora_under_the_model_and_the_users_lora_on_top_of_it():
    # Comfy's template switches a turbo LoRA in to finish the clip in eight
    # steps instead of twenty; here that is the Turbo tick. His own LoRA goes
    # on top of it, so the chain the sampler sees is UNET, turbo, his LoRA.
    wf, payload = _payload(turbo=True, lora="a_look.safetensors", lora_strength=0.8)
    unet = _node_id(payload, "UNETLoader")
    loras = {n: payload[n] for n in payload if payload[n]["class_type"] == "LoraLoaderModelOnly"}
    turbo = next(n for n, node in loras.items() if node.get("_meta", {}).get("title") == "Turbo")
    assert loras[turbo]["inputs"] == {"model": [unet, 0], "strength_model": 1.0,
                                      "lora_name": wf.default_params()["turbo_lora"]}
    his = next(n for n in loras if n != turbo)
    assert loras[his]["inputs"] == {"model": [turbo, 0], "lora_name": "a_look.safetensors",
                                    "strength_model": 0.8}
    guider = payload[_node_id(payload, "BasicGuider")]["inputs"]
    schedule = payload[_node_id(payload, "BasicScheduler")]["inputs"]
    assert guider["model"] == schedule["model"] == [his, 0]

    # Turbo off, no LoRA of his: the sampler runs the bare model.
    _, bare = _payload(turbo=False)
    assert all(node["class_type"] != "LoraLoaderModelOnly" for node in bare.values())
    assert bare[_node_id(bare, "BasicGuider")]["inputs"]["model"] == [_node_id(bare, "UNETLoader"), 0]

    defaults = MiniMaxH3I2vWorkflow().default_params()
    assert defaults["turbo"] is True and defaults["steps"] == 8


def test_a_clips_length_lands_on_h3s_frame_grid_counted_at_24_a_second():
    duration = next(pd for pd in MiniMaxH3I2vWorkflow().param_definitions()
                    if pd.key == "frame_count")
    assert duration.rate == 24.0 and duration.unit == "s"
    assert (duration.min_val, duration.step, duration.max_val) == (5, 17, 362)
    assert duration.options == [5, 10, 15]
    # 5, 10 and 15 seconds typed are the 124, 243 and 362 frames the model
    # renders, and each reads back as the seconds that asked for it.
    for seconds, frames in ((5, 124), (10, 243), (15, 362)):
        assert frames_for_seconds(seconds, 24.0, duration) == frames
        assert seconds_for_frames(frames, 24.0, duration) == seconds
    # Past the fifteen seconds it was trained on, the clip stops where it stops.
    assert frames_for_seconds(30, 24.0, duration) == 362


def test_the_model_and_lora_pickers_offer_only_h3s_first_frame_files(installed_models):
    for category, lora in (("diffusion_models", False), ("loras", True)):
        installed_models.add(category, "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                             arch="minimax_h3", lora=lora)
        installed_models.add(category, "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors",
                             arch="minimax_h3", lora=lora)
        installed_models.add(category, "a_finetune_of_h3.safetensors", arch="minimax_h3", lora=lora)
        installed_models.add(category, "wan22_i2v_high_noise.safetensors", arch="wan", lora=lora)

    by_key = {pd.key: pd for pd in MiniMaxH3I2vWorkflow().param_definitions()}
    assert by_key["unet"].options == ["a_finetune_of_h3.safetensors",
                                      "minimax_h3_fl2va_pruned_int8_convrot.safetensors"]
    assert by_key["lora"].options == ["None", "a_finetune_of_h3.safetensors",
                                      "minimax_h3_fl2va_pruned_int8_convrot.safetensors"]


def test_the_bar_budgets_h3s_one_pass_as_a_video_pass_of_the_clips_frames():
    # The sampler reports the steps its schedule holds, and each step costs
    # what a video step of that many frames costs -- read off the H3
    # conditioning node, the one place the clip's length is a plain number.
    wf, payload = _payload(frame_count=243, steps=8)
    costs = sampler_costs(payload)
    assert set(costs) == {_node_id(payload, "SamplerCustomAdvanced")}
    steps, cost_per_step = next(iter(costs.values()))
    assert steps == 8
    _, short = next(iter(sampler_costs(_payload(frame_count=124, steps=8)[1]).values()))
    assert cost_per_step / short == 243 / 124

    names = stage_names(payload)
    assert names[_node_id(payload, "MiniMaxH3ImageToVideo")] == "Preparing the clip"
    assert names[_node_id(payload, "SamplerCustomAdvanced")] == "Render"
    assert names[_node_id(payload, "VAEDecodeAudio")] == "Decoding sound"


def test_an_h3_graph_reads_back_as_the_h3_workflow_with_its_model_lora_and_turbo():
    wf, payload = _payload(lora="a_look.safetensors", lora_strength=0.8, turbo=True)
    assert _workflow_from_nodes(payload) == "minimax_h3_i2v"
    assert graph_model_params(payload) == {
        "unet": wf.default_params()["unet"], "lora": "a_look.safetensors",
        "lora_strength": 0.8, "turbo": True,
    }
    # With no LoRA of his the turbo LoRA is still the turbo tick, not his LoRA.
    _, bare = _payload(turbo=True)
    assert graph_model_params(bare) == {"unet": wf.default_params()["unet"], "turbo": True}
    _, plain = _payload(turbo=False)
    assert graph_model_params(plain) == {"unet": wf.default_params()["unet"], "turbo": False}


def test_the_file_keeps_h3s_24_frames_a_second_whatever_rate_a_recipe_carries():
    # H3's frames are written exactly as made: there is no Frame Rate on its
    # form, and a rate carried in from another workflow's recipe neither
    # smooths the clip nor changes the speed it plays at.
    wf, payload = _payload(frame_rate=48.0)
    assert "frame_rate" not in wf.default_params()
    assert "frame_rate" not in {pd.key for pd in wf.param_definitions()}
    assert all(node["class_type"] != "RIFE VFI" for node in payload.values())
    assert payload[wf.output_node_id]["inputs"]["frame_rate"] == 24.0


# ---- reference mode: the same person, carried from pictures, videos and sound ----


def _ref_payload(**overrides):
    wf = MiniMaxH3Ref2vWorkflow()
    params = dict(wf.default_params(), input_image="her.png", seed=7, **overrides)
    return wf, wf.build_api_payload(params)


def test_reference_to_video_is_h3s_second_workflow_on_its_own_checkpoint():
    wf = WORKFLOW_REGISTRY["minimax_h3_ref2v"]
    assert isinstance(wf, MiniMaxH3Ref2vWorkflow)
    assert wf.selectable and wf.output_type == "video"
    assert wf.display_name == "MiniMax H3 Reference-to-Video"
    assert wf.native_fps == 24.0 and wf.size_stride == 32 and wf.derives_size_from_input
    defaults = wf.default_params()
    assert defaults["unet"] == "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors"
    assert defaults["turbo_lora"] == "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    # Comfy's guide: the four-step turbo barely applies the references, so a
    # reference shot runs the full schedule unless the tick is turned on.
    assert defaults["turbo"] is False and defaults["steps"] == 20


def test_the_reference_graph_hands_every_reference_to_the_one_h3_reference_node():
    # The reference picture leads the pictures; every further picture, video
    # and sound gets a loader of its own and lands in the node's numbered slots
    # (``ref_images.ref_image_1``, ``ref_videos.ref_video_0``...), a video's
    # soundtrack beside its frames; the canvas is the reference picture's
    # shape at the video budget.
    wf, payload = _ref_payload(
        positive_prompt="<Picture 1> walks in and laughs like <Audio 1>",
        ref_images=["her_too.png"], ref_videos=["her_talking.mp4"], ref_audios=["her_voice.wav"],
        frame_count=243)
    node = payload[_node_id(payload, "MiniMaxH3ReferenceToVideo")]["inputs"]
    assert node["prompt"] == "<Picture 1> walks in and laughs like <Audio 1>"
    assert node["length"] == 243 and node["ref_image_size"] == "match"
    assert node["clip"] == [_node_id(payload, "CLIPLoader"), 0]
    vaes = {payload[n]["inputs"]["vae_name"]: n for n in payload
            if payload[n]["class_type"] == "VAELoader"}
    assert node["vae"] == [vaes[wf.default_params()["vae_name"]], 0]
    assert node["audio_vae"] == [vaes[wf.default_params()["audio_vae_name"]], 0]

    pictures = {payload[n]["inputs"]["image"]: n for n in payload
                if payload[n]["class_type"] == "LoadImage"}
    assert node["ref_images.ref_image_0"] == [pictures["her.png"], 0]
    assert node["ref_images.ref_image_1"] == [pictures["her_too.png"], 0]
    video = _node_id(payload, "LoadVideo")
    assert payload[video]["inputs"] == {"file": "her_talking.mp4"}
    parts = _node_id(payload, "GetVideoComponents")
    assert payload[parts]["inputs"] == {"video": [video, 0]}
    assert node["ref_videos.ref_video_0"] == [parts, 0]
    assert node["ref_video_audios.ref_video_audio_0"] == [parts, 1]
    sound = _node_id(payload, "LoadAudio")
    assert payload[sound]["inputs"] == {"audio": "her_voice.wav"}
    assert node["ref_audios.ref_audio_0"] == [sound, 0]
    assert not any(key.startswith("ref_") and key.endswith("_2") for key in node)

    size = _node_id(payload, "GetImageSize")
    assert (node["width"], node["height"]) == ([size, 0], [size, 1])
    assert payload[_node_id(payload, "ImageScaleToTotalPixels")]["inputs"]["image"] == [pictures["her.png"], 0]

    sampler = payload[_node_id(payload, "SamplerCustomAdvanced")]["inputs"]
    assert sampler["latent_image"] == [_node_id(payload, "MiniMaxH3ReferenceToVideo"), 1]
    assert payload[sampler["guider"][0]]["inputs"]["conditioning"] == [_node_id(payload, "MiniMaxH3ReferenceToVideo"), 0]
    assert payload[wf.output_node_id]["inputs"]["frame_rate"] == 24.0


def test_a_reference_shot_from_one_picture_carries_only_that_picture():
    wf, payload = _ref_payload()
    node = payload[_node_id(payload, "MiniMaxH3ReferenceToVideo")]["inputs"]
    assert [key for key in node if key.startswith("ref_")] == ["ref_image_size", "ref_images.ref_image_0"]
    assert not {node["class_type"] for node in payload.values()} & {"LoadVideo", "LoadAudio"}


def test_the_reference_pickers_offer_only_h3s_reference_files(installed_models):
    for category, lora in (("diffusion_models", False), ("loras", True)):
        installed_models.add(category, "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                             arch="minimax_h3", lora=lora)
        installed_models.add(category, "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors",
                             arch="minimax_h3", lora=lora)
        installed_models.add(category, "wan22_i2v_high_noise.safetensors", arch="wan", lora=lora)
    by_key = {pd.key: pd for pd in MiniMaxH3Ref2vWorkflow().param_definitions()}
    assert by_key["unet"].options == ["MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors"]
    assert by_key["lora"].options == ["None", "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors"]
    assert by_key["input_image"].label == "Reference Picture"
