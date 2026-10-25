from __future__ import annotations

import json

import pytest

from origenerator.gallery.tree import folder_chain
from origenerator.workflows import WORKFLOW_REGISTRY

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
