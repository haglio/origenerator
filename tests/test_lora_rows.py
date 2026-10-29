from __future__ import annotations

import json

import pytest

from origenerator.gallery.labels import lora_label
from origenerator.gallery.tree import folder_chain
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.model_files import NO_LORA

_STORED_VALUES = {
    "audio_encoder_name": "a_wav2vec.safetensors", "audio_negative_prompt": "hiss",
    "audio_prompt": "waves on shingle", "audio_seed": 3, "batch_size": 1, "cfg": 5.0,
    "cfg_high": 3.5, "cfg_low": 3.0, "checkpoint": "a_checkpoint.safetensors",
    "clip_name": "a_text_encoder.safetensors", "clip_name1": "a_clip.safetensors",
    "clip_name2": "a_t5.safetensors", "clip_vision_name": "a_clip_vision.safetensors",
    "control_mode": "depth", "controlnet": "a_controlnet.safetensors", "controlnet_end": 1.0,
    "controlnet_strength": 0.8, "denoise": 1.0, "depth_model": "a_depth_model.safetensors",
    "enhance": False, "enhance_denoise": 0.15, "enhance_scale": 2.0, "enhance_steps": 20,
    "filename_prefix": "fabricated/prefix", "foley_model": "a_foley_model.safetensors",
    "foley_synchformer": "a_synchformer.safetensors", "foley_vae": "a_foley_vae.safetensors",
    "frame_count": 81, "frame_rate": 16.0, "guidance": 3.5, "height": 768,
    "input_image": "example_start.png", "lora": "None", "lora_high": "None", "lora_low": "None",
    "lora_strength": 0.7, "lora_strength_high": 0.9, "lora_strength_low": 0.8,
    "negative_prompt": "blurry", "noise_seed": 5, "pose_bbox_detector": "a_person_detector.onnx",
    "pose_estimator": "a_pose_estimator.pt", "positive_prompt": "a lighthouse at dusk",
    "sampler_name": "euler", "scene_frames": [81], "scene_lines": [""], "scheduler": "simple",
    "seed": 7, "shift": 8.0, "shift_high": 8.0, "shift_low": 8.0, "split_step": 0, "steps": 20,
    "unet": "a_unet.safetensors", "unet_high": "a_high_unet.safetensors",
    "unet_low": "a_low_unet.safetensors", "unet_s2v": "a_speech_unet.safetensors",
    "upscale_model": "an_upscaler.pt", "vae": "a_vae.safetensors",
    "vae_name": "a_video_vae.safetensors", "video": "example_moves.mp4", "video_start": 0.0,
    "voice": "a_voice", "voice_sample": "", "voice_sample_text": "", "width": 1024,
}

_STORED_KEYS = {
    "sdxl_t2i": "batch_size cfg checkpoint denoise enhance enhance_denoise enhance_scale "
                "enhance_steps filename_prefix height negative_prompt positive_prompt "
                "sampler_name scheduler seed steps upscale_model vae width",
    "sdxl_pose_transfer": "batch_size cfg checkpoint control_mode controlnet controlnet_end "
                          "controlnet_strength denoise depth_model enhance enhance_denoise "
                          "enhance_scale enhance_steps filename_prefix input_image "
                          "negative_prompt pose_bbox_detector pose_estimator positive_prompt "
                          "sampler_name scheduler seed steps upscale_model vae",
    "krea2_t2i": "batch_size cfg clip_name enhance enhance_denoise enhance_scale enhance_steps "
                 "filename_prefix height lora lora_strength negative_prompt positive_prompt "
                 "sampler_name scheduler seed steps unet upscale_model vae width",
    "flux_t2i_upscaled": "batch_size cfg clip_name1 clip_name2 denoise enhance enhance_denoise "
                         "enhance_scale enhance_steps filename_prefix guidance height lora "
                         "lora_strength negative_prompt positive_prompt sampler_name scheduler "
                         "seed steps unet upscale_model vae width",
    "wan22_animate": "batch_size cfg clip_name clip_vision_name filename_prefix frame_count "
                     "frame_rate input_image lora lora_strength negative_prompt positive_prompt "
                     "sampler_name scheduler seed shift steps unet vae_name video video_start",
    "wan22_i2v": "audio_encoder_name audio_negative_prompt audio_prompt audio_seed batch_size "
                 "cfg_high cfg_low clip_name clip_vision_name filename_prefix foley_model "
                 "foley_synchformer foley_vae frame_count frame_rate input_image lora_high "
                 "lora_low lora_strength_high lora_strength_low negative_prompt noise_seed "
                 "positive_prompt sampler_name scene_frames scene_lines scheduler seed "
                 "shift_high shift_low split_step steps unet_high unet_low unet_s2v vae_name "
                 "voice voice_sample voice_sample_text",
    "wan22_flf2v_loop": "audio_negative_prompt audio_prompt audio_seed batch_size cfg clip_name "
                        "filename_prefix foley_model foley_synchformer foley_vae frame_count "
                        "frame_rate input_image lora_high lora_low lora_strength_high "
                        "lora_strength_low negative_prompt noise_seed positive_prompt "
                        "sampler_name scene_frames scheduler seed shift_high shift_low steps "
                        "unet_high unet_low vae_name",
}

_A_LORA = {"lora": "example_style.safetensors"}
_A_PAIR = {"lora_high": "example_high.safetensors", "lora_low": "example_low.safetensors"}

_FOLDERS_RUNS_WERE_FILED_IN = [
    ("sdxl_t2i", {}, ("meda56f468e15", "l0c7fd072a68f", "8c155f7f2194")),
    ("sdxl_pose_transfer", {}, ("meda56f468e15", "l0c7fd072a68f", "99c08fe4938e")),
    ("krea2_t2i", {}, ("m079c29540fbf", "l407c4a0fc6ad", "234bd34e0e63")),
    ("krea2_t2i", _A_LORA, ("m079c29540fbf", "l1c55b892b7ca", "05d71e5d1076")),
    ("flux_t2i_upscaled", {}, ("m079c29540fbf", "l407c4a0fc6ad", "a42f1ed61f35")),
    ("flux_t2i_upscaled", _A_LORA, ("m079c29540fbf", "l1c55b892b7ca", "88bd90ef3961")),
    ("wan22_animate", {}, ("m079c29540fbf", "l407c4a0fc6ad", "i3eddda01f4bb", "8b10c7077f3e")),
    ("wan22_animate", _A_LORA, ("m079c29540fbf", "l1c55b892b7ca", "i263e65277a11",
                                "ff6197a55233")),
    ("wan22_i2v", {}, ("mfad46dc0b66b", "lbd6e1133c40f", "i7d8c5568cc8d", "9dbccbe18525")),
    ("wan22_i2v", _A_PAIR, ("mfad46dc0b66b", "l435b811b4bf1", "i093d2cb243b9", "d858c1afa73b")),
    ("wan22_flf2v_loop", {}, ("mfad46dc0b66b", "lbd6e1133c40f", "i7d8c5568cc8d",
                              "f058c1ce72c6")),
    ("wan22_flf2v_loop", _A_PAIR, ("mfad46dc0b66b", "l435b811b4bf1", "i093d2cb243b9",
                                   "b04f0bae7e7c")),
]


def _stored_run(name: str, picked: dict) -> dict:
    return {key: _STORED_VALUES[key] for key in _STORED_KEYS[name].split()} | picked


def _folders(name: str, params: dict) -> tuple[str, ...]:
    row = {"workflow_name": name, "workflow_version": WORKFLOW_REGISTRY[name].version,
           "params_json": json.dumps(params)}
    return tuple(key.rpartition("/")[2] for key in folder_chain(row, {})[3:])


@pytest.mark.parametrize(("name", "picked", "folders"), _FOLDERS_RUNS_WERE_FILED_IN)
def test_a_stored_run_keeps_the_folders_it_was_filed_in(name, picked, folders):
    assert _folders(name, _stored_run(name, picked)) == folders


_THREE_LORA_WORKFLOWS = ("sdxl_t2i", "sdxl_pose_transfer", "krea2_t2i", "flux_t2i_upscaled",
                         "wan22_animate")


@pytest.mark.parametrize("name", _THREE_LORA_WORKFLOWS)
def test_a_form_offers_three_loras_each_on_none_above_its_own_strength(name):
    rows = [(pd.key, pd.label, pd.default, pd.good)
            for pd in WORKFLOW_REGISTRY[name].param_definitions() if pd.key.startswith("lora")]

    assert rows == [
        ("lora", "LoRA 1", "None", None), ("lora_strength", "LoRA Strength 1", 1.0, (0.6, 1.2)),
        ("lora_2", "LoRA 2", "None", None), ("lora_strength_2", "LoRA Strength 2", 1.0, (0.6, 1.2)),
        ("lora_3", "LoRA 3", "None", None), ("lora_strength_3", "LoRA Strength 3", 1.0, (0.6, 1.2)),
    ]


_TWO_PASS_WORKFLOWS = ("wan22_i2v", "wan22_flf2v_loop")


@pytest.mark.parametrize("name", _TWO_PASS_WORKFLOWS)
@pytest.mark.parametrize("key", ["lora_high_2", "lora_high_3", "lora_low_2", "lora_low_3"])
def test_a_lora_picked_on_any_row_of_a_pass_is_filed_under_a_lora_folder_naming_it(name, key):
    stored = _stored_run(name, _A_PAIR)
    picked = stored | {key: "example_extra.safetensors"}

    assert _folders(name, picked)[1] != _folders(name, stored)[1]
    assert "example_extra" in lora_label(name, picked).split(" / ")


@pytest.mark.parametrize("name", _TWO_PASS_WORKFLOWS)
def test_a_two_pass_form_offers_three_loras_for_each_pass_the_first_pass_first(name):
    workflow = WORKFLOW_REGISTRY[name]
    defaults = workflow.default_params()
    rows = [(pd.key, pd.label, pd.default)
            for pd in workflow.param_definitions() if pd.key.startswith("lora")]

    assert rows == [
        ("lora_high", "LoRA 1 (First Pass)", defaults["lora_high"]),
        ("lora_strength_high", "LoRA Strength 1 (First Pass)", 1.0),
        ("lora_high_2", "LoRA 2 (First Pass)", "None"),
        ("lora_strength_high_2", "LoRA Strength 2 (First Pass)", 1.0),
        ("lora_high_3", "LoRA 3 (First Pass)", "None"),
        ("lora_strength_high_3", "LoRA Strength 3 (First Pass)", 1.0),
        ("lora_low", "LoRA 1 (Second Pass)", defaults["lora_low"]),
        ("lora_strength_low", "LoRA Strength 1 (Second Pass)", 1.0),
        ("lora_low_2", "LoRA 2 (Second Pass)", "None"),
        ("lora_strength_low_2", "LoRA Strength 2 (Second Pass)", 1.0),
        ("lora_low_3", "LoRA 3 (Second Pass)", "None"),
        ("lora_strength_low_3", "LoRA Strength 3 (Second Pass)", 1.0),
    ]


@pytest.mark.parametrize("name", _THREE_LORA_WORKFLOWS)
def test_a_forms_loras_come_right_after_its_model(name):
    workflow = WORKFLOW_REGISTRY[name]
    keys = [pd.key for pd in workflow.param_definitions()]
    model = keys.index(workflow.model_keys[0])

    assert keys[model + 1:model + 7] == [
        "lora", "lora_strength", "lora_2", "lora_strength_2", "lora_3", "lora_strength_3"]


_FAMILIES_A_GRAPH_RUNS = {
    "sdxl_t2i": ("sd15", "sdxl"), "sdxl_pose_transfer": ("sd15", "sdxl"),
    "krea2_t2i": ("krea2",), "flux_t2i_upscaled": ("flux",), "wan22_animate": ("wan",),
}


@pytest.mark.parametrize("name", _THREE_LORA_WORKFLOWS)
def test_every_lora_on_a_form_offers_only_the_loras_its_graph_can_run(name, installed_models):
    for family in ("sdxl", "sd15", "krea2", "flux", "wan"):
        installed_models.add("loras", f"fam_{family}.safetensors", arch=family, lora=True)

    offered = {pd.key: pd.options for pd in WORKFLOW_REGISTRY[name].param_definitions()}

    runnable = [NO_LORA, *(f"fam_{family}.safetensors" for family in _FAMILIES_A_GRAPH_RUNS[name])]
    assert [offered[key] for key in ("lora", "lora_2", "lora_3")] == [runnable] * 3


@pytest.mark.parametrize(("name", "picked", "folders"), _FOLDERS_RUNS_WERE_FILED_IN)
def test_a_run_that_leaves_the_added_loras_on_none_joins_the_folders_runs_had_before(
        name, picked, folders):
    stored = _stored_run(name, picked)
    added = {key: value for key, value in WORKFLOW_REGISTRY[name].default_params().items()
             if key not in stored}
    turned = {key: 0.5 for key in added if key.startswith("lora_strength")}

    assert _folders(name, stored | added) == folders
    assert _folders(name, stored | added | turned) == folders


_LORA_LOADERS = ("LoraLoader", "LoraLoaderModelOnly")
_THREADS_THE_TEXT_ENCODER = ("sdxl_t2i", "sdxl_pose_transfer", "flux_t2i_upscaled")


def _sampler(payload: dict) -> dict:
    return next(node for node in payload.values() if node["class_type"] == "KSampler")


def _loras_behind(payload: dict, ref, through: str) -> list[tuple[str, float]]:
    loras = []
    node = payload.get(ref[0]) if isinstance(ref, list) else None
    while node is not None:
        if node["class_type"] in _LORA_LOADERS:
            loras.append((node["inputs"]["lora_name"], node["inputs"]["strength_model"]))
        ref = node["inputs"].get(through)
        node = payload.get(ref[0]) if isinstance(ref, list) else None
    return loras[::-1]


def _users_loras(name: str, picked: dict) -> list[tuple[str, float]]:
    workflow = WORKFLOW_REGISTRY[name]

    def loras(params: dict) -> list[tuple[str, float]]:
        payload = workflow.build_api_payload(params)
        return _loras_behind(payload, _sampler(payload)["inputs"]["model"], "model")

    return loras(workflow.default_params() | picked)[len(loras(workflow.default_params())):]


@pytest.mark.parametrize("name", _THREE_LORA_WORKFLOWS)
def test_two_loras_picked_together_both_reach_the_sampler_one_after_the_other(name):
    picked = {"lora": "first_look.safetensors", "lora_strength": 0.7,
              "lora_3": "second_look.safetensors", "lora_strength_3": 0.6}

    assert _users_loras(name, picked) == [("first_look.safetensors", 0.7),
                                          ("second_look.safetensors", 0.6)]


@pytest.mark.parametrize("name", _THREADS_THE_TEXT_ENCODER)
def test_two_loras_picked_together_both_reach_the_prompts_one_after_the_other(name):
    workflow = WORKFLOW_REGISTRY[name]
    payload = workflow.build_api_payload(workflow.default_params() | {
        "lora_2": "first_look.safetensors", "lora_strength_2": 0.7,
        "lora_3": "second_look.safetensors", "lora_strength_3": 0.6})

    readers = [node["inputs"]["clip"] for node in payload.values()
               if node["class_type"] == "CLIPTextEncode"]
    assert readers and all(_loras_behind(payload, clip, "clip") == [
        ("first_look.safetensors", 0.7), ("second_look.safetensors", 0.6)] for clip in readers)


def _each_pass_loras(payload: dict) -> dict[str, list[list[tuple[str, float]]]]:
    passes: dict[str, list[list[tuple[str, float]]]] = {"enable": [], "disable": []}
    for node in payload.values():
        if node["class_type"] == "KSamplerAdvanced":
            passes[node["inputs"]["add_noise"]].append(
                _loras_behind(payload, node["inputs"]["model"], "model"))
    return passes


@pytest.mark.parametrize("name", _TWO_PASS_WORKFLOWS)
def test_loras_picked_together_on_a_pass_all_reach_its_sampler_one_after_the_other(name):
    workflow = WORKFLOW_REGISTRY[name]
    payload = workflow.build_api_payload(workflow.default_params() | {
        "lora_high": "first_motion.safetensors", "lora_strength_high": 0.9,
        "lora_high_3": "second_motion.safetensors", "lora_strength_high_3": 0.6,
        "lora_low": NO_LORA,
        "lora_low_2": "first_detail.safetensors", "lora_strength_low_2": 0.7,
        "lora_low_3": "second_detail.safetensors", "lora_strength_low_3": 0.5})

    passes = _each_pass_loras(payload)
    assert passes["enable"] and all(loras == [("first_motion.safetensors", 0.9),
                                              ("second_motion.safetensors", 0.6)]
                                    for loras in passes["enable"])
    assert passes["disable"] and all(loras == [("first_detail.safetensors", 0.7),
                                               ("second_detail.safetensors", 0.5)]
                                     for loras in passes["disable"])


@pytest.mark.parametrize("name", _THREE_LORA_WORKFLOWS)
def test_a_lora_left_on_none_adds_nothing_to_the_graph(name):
    assert _users_loras(name, {}) == []
    assert _users_loras(name, {"lora_2": "a_look.safetensors", "lora_strength_2": 0.8}) == [
        ("a_look.safetensors", 0.8)]
