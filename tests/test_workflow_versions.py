from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import re

import pytest

from origenerator.workflows import (
    WORKFLOW_REGISTRY,
    base,
    detail_parts,
    model_files,
    wan22_i2v,
)


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def _rounded(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def _fingerprint(payload: dict) -> str:
    nodes: dict[str, str] = {}

    def node(node_id: str) -> str:
        if node_id not in nodes:
            built = payload[node_id]
            nodes[node_id] = _digest([
                built["class_type"],
                {name: wired(value) for name, value in built["inputs"].items()},
            ])
        return nodes[node_id]

    def wired(value):
        if (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
                and value[0] in payload and isinstance(value[1], int)):
            return {"output": value[1], "of": node(value[0])}
        if isinstance(value, str) and value.startswith(("[", "{")):
            with contextlib.suppress(ValueError):
                return {"document": _rounded(json.loads(value))}
        return _rounded(value)

    return _digest(sorted(node(node_id) for node_id in payload))


def test_a_graphs_fingerprint_does_not_care_what_its_nodes_are_called():
    numbered = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "2": {"class_type": "ImageScaleBy", "inputs": {"image": ["1", 0], "scale_by": 2.0}},
    }
    named = {
        "scaled": {"class_type": "ImageScaleBy",
                   "inputs": {"image": ["loaded", 0], "scale_by": 2.0}},
        "loaded": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
    }

    assert _fingerprint(numbered) == _fingerprint(named)


def test_a_graphs_fingerprint_follows_what_each_input_is_wired_to():
    loaded = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
    }
    joined = {**loaded, "3": {"class_type": "ImageBatch",
                              "inputs": {"image1": ["1", 0], "image2": ["2", 0]}}}
    swapped = {**loaded, "3": {"class_type": "ImageBatch",
                               "inputs": {"image1": ["2", 0], "image2": ["1", 0]}}}

    assert _fingerprint(joined) != _fingerprint(swapped)


def test_float_noise_past_the_sixth_decimal_moves_no_fingerprint():
    def tracked(y: float, temperature: float) -> dict:
        return {"1": {"class_type": "WanTrackToVideo", "inputs": {
            "tracks": json.dumps([[{"x": 240.0, "y": y}]]),
            "temperature": temperature,
        }}}

    settled = _fingerprint(tracked(178.873796, 220.0))

    assert _fingerprint(tracked(178.873796 + 1e-11, 220.0 + 1e-11)) == settled
    assert _fingerprint(tracked(178.874, 220.0)) != settled


_PINNED = {
    "anchor_x": 250,
    "anchor_y": 700,
    "audio_encoder_name": "an_audio_encoder.safetensors",
    "audio_negative_prompt": "hiss",
    "audio_prompt": "waves on shingle",
    "audio_seed": 103,
    "batch_size": 1,
    "cfg": 6.5,
    "cfg_high": 3.25,
    "cfg_low": 2.75,
    "checkpoint": "a_checkpoint.safetensors",
    "clip_name": "a_text_encoder.safetensors",
    "clip_name1": "a_clip.safetensors",
    "clip_name2": "a_t5.safetensors",
    "clip_vision_name": "a_clip_vision.safetensors",
    "control_mode": "depth",
    "controlnet": "a_controlnet.safetensors",
    "controlnet_end": 0.9,
    "controlnet_strength": 0.75,
    "crf": 21,
    "denoise": 1.0,
    "depth_model": "a_depth_model.safetensors",
    "enhance": False,
    "enhance_denoise": 0.2,
    "enhance_detail_fixes": {},
    "enhance_scale": 1.5,
    "enhance_steps": 12,
    "filename_prefix": "fingerprinted",
    "foley_model": "a_foley_model.safetensors",
    "foley_synchformer": "a_synchformer.safetensors",
    "foley_vae": "a_foley_vae.safetensors",
    "frame_count": 81,
    "frame_rate": 16.0,
    "guidance": 3.5,
    "height": 768,
    "input_image": "",
    "length": 5,
    "lora_high": "a_high_lora.safetensors",
    "lora_low": "a_low_lora.safetensors",
    "lora_strength_high": 0.9,
    "lora_strength_low": 0.7,
    "motion_ceiling": 420,
    "motion_floor": 610,
    "motion_hz": 1.1,
    "motion_x": 240,
    "negative_prompt": "blurry",
    "noise_seed": 102,
    "pose_bbox_detector": "a_person_detector.onnx",
    "pose_estimator": "a_pose_estimator.pt",
    "positive_prompt": "a lighthouse at dusk",
    "sampler_name": "dpmpp_2m",
    "scene_frames": [81],
    "scene_lines": [""],
    "scheduler": "karras",
    "seed": 101,
    "shift": 7.0,
    "shift_high": 6.5,
    "shift_low": 5.5,
    "split_step": 10,
    "steps": 24,
    "unet": "a_unet.safetensors",
    "unet_high": "a_high_unet.safetensors",
    "unet_low": "a_low_unet.safetensors",
    "unet_s2v": "a_speech_unet.safetensors",
    "upscale_model": "an_upscaler.pt",
    "vae": "a_vae.safetensors",
    "vae_name": "a_video_vae.safetensors",
    "voice": "Vivian",
    "voice_sample": "",
    "voice_sample_text": "",
    "width": 1024,
}

_VARIATIONS = {
    "as pinned": {},
    "enhanced, with faces and hands fixed": {
        "enhance": True,
        "enhance_detail_fixes": {"faces": 0.4, "hands": 0.55},
    },
    "a spoken story, chained and smoothed": {
        "positive_prompt": "a quiet harbor\n---\nthe tide comes in",
        "negative_prompt": "blurry\n---\ncrowded",
        "frame_count": 321,
        "scene_frames": [81, 241],
        "scene_lines": ["", "the tide is turning"],
        "frame_rate": 48.0,
    },
    "with both LoRAs bypassed": {"lora_high": "None", "lora_low": "None"},
    "sized by hand": {"width": 832, "height": 480},
    "posed from a skeleton, through a union ControlNet": {
        "control_mode": "pose",
        "controlnet": "a_union_controlnet.safetensors",
    },
}

_INSTALLED_DETECTORS = ("face_detector.pt", "hand_detector.pt")

# Changing the recipes above moves these without any graph changing: re-record
# every fingerprint that moves, and bump no version for it.
GRAPH_FINGERPRINTS = {
    ("flux_t2i_upscaled", "v002"): "f02c9827d96c9fc1",
    ("image_enhance", "v003"): "228ccee5269454ec",
    ("sdxl_pose_transfer", "v004"): "067f07b0440388d9",
    ("sdxl_t2i", "v004"): "906cfa8824d0524d",
    ("wan21_ati_i2v", "v007"): "c82a130aa21d7352",
    ("wan22_flf2v_loop", "v009"): "3cc07d12a40c7995",
    ("wan22_i2v", "v007"): "ce72e0c5e1342c10",
    ("wan22_t2i", "v002"): "f0794cae55c3e05d",
}


def _variation_fingerprint(workflow, variation: dict) -> str:
    pinned = {key: _PINNED[key] for key in workflow.default_params()}
    return _fingerprint(workflow.build_api_payload(copy.deepcopy({**pinned, **variation})))


def _workflow_fingerprint(workflow) -> str:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(detail_parts, "list_detector_files", lambda: list(_INSTALLED_DETECTORS))
        graphs = {_variation_fingerprint(workflow, variation) for variation in _VARIATIONS.values()}
    return _digest(sorted(graphs))


def _what_to_record(name: str, version: str, recorded: str | None, built: str) -> str:
    if recorded is None:
        return (f"no graph fingerprint is recorded for {name} {version}: put "
                f"({name!r}, {version!r}): {built!r} in GRAPH_FINGERPRINTS, in place "
                f"of any entry an older version of {name} left there")
    bumped = re.sub(r"\d+$", lambda digits: f"{int(digits[0]) + 1:0{len(digits[0])}d}",
                    version)
    return (f"{name}'s graph changed while its version stayed {version} (recorded "
            f"{recorded}, built {built}): bump its version to {bumped}, and put "
            f"({name!r}, {bumped!r}): {built!r} in GRAPH_FINGERPRINTS in place of "
            f"the {version} entry")


@pytest.mark.parametrize("name", sorted(WORKFLOW_REGISTRY))
def test_a_workflows_graph_changes_only_with_its_version(name):
    workflow = WORKFLOW_REGISTRY[name]

    built = _workflow_fingerprint(workflow)
    recorded = GRAPH_FINGERPRINTS.get((name, workflow.version))

    assert built == recorded, _what_to_record(name, workflow.version, recorded, built)


@pytest.mark.parametrize(("name", "change"), [
    pytest.param("sdxl_t2i",
                 lambda patch: patch.setattr(base, "UPSCALE_MODEL_FACTOR", 2.0),
                 id="the enhance tail"),
    pytest.param("image_enhance",
                 lambda patch: patch.setattr(base, "_DETAIL_FEATHER", 9),
                 id="a fix pass"),
    pytest.param("wan22_flf2v_loop",
                 lambda patch: patch.setattr(base, "SINGLE_WINDOW_FRAMES", 81),
                 id="a chained segment"),
    pytest.param("wan22_i2v",
                 lambda patch: patch.setattr(wan22_i2v, "_SPEECH_STEPS", 8),
                 id="a spoken scene"),
    pytest.param("wan21_ati_i2v",
                 lambda patch: patch.setattr(base, "RIFE_CHECKPOINT", "another_rife.pth"),
                 id="the frames made in between"),
    pytest.param("wan22_i2v",
                 lambda patch: patch.setattr(model_files, "NO_LORA", "Nothing"),
                 id="a bypassed LoRA"),
    pytest.param("wan22_flf2v_loop",
                 lambda patch: patch.setattr(base, "override_size", lambda params: None),
                 id="a size set by hand"),
    pytest.param("sdxl_pose_transfer",
                 lambda patch: patch.setitem(_PINNED, "pose_estimator", "another_estimator.pt"),
                 id="a pose skeleton"),
])
def test_a_change_to_a_part_the_pinned_recipe_leaves_out_still_moves_the_fingerprint(
        name, change, monkeypatch):
    workflow = WORKFLOW_REGISTRY[name]
    pinned_graph = _variation_fingerprint(workflow, {})
    before = _workflow_fingerprint(workflow)

    change(monkeypatch)

    assert _variation_fingerprint(workflow, {}) == pinned_graph
    assert _workflow_fingerprint(workflow) != before


def test_the_gates_tables_hold_nothing_the_registry_has_dropped():
    current = {(name, workflow.version) for name, workflow in WORKFLOW_REGISTRY.items()}
    taken = {key for workflow in WORKFLOW_REGISTRY.values() for key in workflow.default_params()}

    assert set(GRAPH_FINGERPRINTS) - current == set()
    assert set(_PINNED) - taken == set()
