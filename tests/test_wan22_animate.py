from __future__ import annotations

from pathlib import Path

import pytest

import origenerator.workflows.model_dropdowns as dropdowns
import origenerator.workflows.wan22_animate as animate
from origenerator import config
from origenerator.funscript import write_funscript
from origenerator.workflows.derived_size import scale_to_total_pixels
from origenerator.workflows.driving_video import driven_actions
from origenerator.workflows.frame_rate import NATIVE_FPS
from origenerator.workflows.model_arch import WAN, WAN_ANIMATE
from origenerator.workflows.model_files import NO_LORA
from origenerator.workflows.wan22_animate import DISTILL_LORA, Wan22AnimateWorkflow

VIDEO = "C:/library/videos/videos/2D/sample/scene one.mp4"


def _params(**overrides) -> dict:
    wf = Wan22AnimateWorkflow()
    return {**wf.default_params(), "input_image": "performer.png", "video": VIDEO,
            "video_start": 2.0, "frame_count": 81, "seed": 5, **overrides}


def _payload(**overrides) -> dict:
    return Wan22AnimateWorkflow().build_api_payload(_params(**overrides))


def _nodes(payload: dict, class_type: str) -> list[tuple[str, dict]]:
    return [(node_id, node) for node_id, node in payload.items()
            if node["class_type"] == class_type]


def _node(payload: dict, class_type: str) -> tuple[str, dict]:
    (found,) = _nodes(payload, class_type)
    return found


def test_the_workflow_is_a_video_from_an_image_sized_off_its_inputs():
    wf = Wan22AnimateWorkflow()
    assert wf.name == "wan22_animate"
    assert wf.output_type == "video"
    assert wf.derives_size_from_input
    assert wf.derived_size_source == "video"
    assert wf.model_keys == ("unet",)
    assert wf.lora_keys == ("lora", "lora_2", "lora_3")
    assert wf.seed_keys() == ("seed",)
    assert "animate" not in wf.display_name.lower()


def test_the_run_reads_the_library_video_from_its_start_at_the_models_rate_for_the_clips_frames():
    _loader_id, loader = _node(_payload(), "VHS_LoadVideoPath")
    assert loader["inputs"] == {
        "video": VIDEO,
        "force_rate": NATIVE_FPS,
        "custom_width": 0,
        "custom_height": 0,
        "frame_load_cap": 81,
        "skip_first_frames": 32,       # 2.0 s at 16 fps
        "select_every_nth": 1,
        "format": "None",
    }


def test_the_output_size_is_derived_from_the_video_and_both_inputs_are_fitted_into_it():
    payload = _payload()
    loader_id, _ = _node(payload, "VHS_LoadVideoPath")
    first_frame_id, first_frame = _node(payload, "ImageFromBatch")
    assert first_frame["inputs"] == {"image": [loader_id, 0], "batch_index": 0, "length": 1}
    scale = payload["size_scale"]
    assert scale["class_type"] == "ImageScaleToTotalPixels"
    assert scale["inputs"]["image"] == [first_frame_id, 0]
    width, height = ["size_get", 0], ["size_get", 1]

    _fitted_id, fitted_frames = _node(payload, "ImageScale")
    assert fitted_frames["inputs"] == {"image": [loader_id, 0], "upscale_method": "lanczos",
                                       "width": width, "height": height, "crop": "center"}
    image_id, image = _node(payload, "LoadImage")
    assert image["inputs"] == {"image": "performer.png"}
    _fitted_image_id, fitted_image = _node(payload, "ImageResizeKJv2")
    assert fitted_image["inputs"]["image"] == [image_id, 0]
    assert fitted_image["inputs"]["keep_proportion"] == "pillarbox_blur"
    assert (fitted_image["inputs"]["width"], fitted_image["inputs"]["height"]) == (width, height)


def test_the_pose_and_the_face_are_read_off_the_fitted_frames_at_the_frames_own_resolution():
    payload = _payload()
    fitted_id, _ = _node(payload, "ImageScale")
    resolution_id, resolution = _node(payload, "PixelPerfectResolution")
    assert resolution["inputs"] == {"original_image": [fitted_id, 0], "image_gen_width": ["size_get", 0],
                                    "image_gen_height": ["size_get", 1], "resize_mode": "Just Resize"}
    detectors = {node["inputs"]["detect_face"]: node["inputs"] for _, node in _nodes(payload, "DWPreprocessor")}
    pose, face = detectors["disable"], detectors["enable"]
    assert (pose["detect_body"], pose["detect_hand"]) == ("enable", "enable")
    assert (face["detect_body"], face["detect_hand"]) == ("disable", "disable")
    for detector in (pose, face):
        assert detector["image"] == [fitted_id, 0]
        assert detector["resolution"] == [resolution_id, 0]
        assert detector["bbox_detector"] == "yolox_l.torchscript.pt"
        assert detector["pose_estimator"] == "dw-ll_ucoco_384_bs5.torchscript.pt"


def test_the_animate_node_is_handed_the_image_the_pose_and_the_face_for_the_clips_frames():
    payload = _payload()
    image_id, _ = _node(payload, "LoadImage")
    fitted_image_id, _ = _node(payload, "ImageResizeKJv2")
    vision_id, vision = _node(payload, "CLIPVisionEncode")
    assert vision["inputs"] == {"clip_vision": ["3", 0], "image": [image_id, 0], "crop": "none"}
    pose_id = next(node_id for node_id, node in _nodes(payload, "DWPreprocessor")
                   if node["inputs"]["detect_face"] == "disable")
    face_id = next(node_id for node_id, node in _nodes(payload, "DWPreprocessor")
                   if node["inputs"]["detect_face"] == "enable")

    _animate_id, node = _node(payload, "WanAnimateToVideo")
    assert node["inputs"] == {
        "positive": ["8", 0], "negative": ["9", 0], "vae": ["2", 0],
        "width": ["size_get", 0], "height": ["size_get", 1], "length": 81, "batch_size": 1,
        "clip_vision_output": [vision_id, 0], "reference_image": [fitted_image_id, 0],
        "face_video": [face_id, 0], "pose_video": [pose_id, 0],
        "continue_motion_max_frames": 1, "video_frame_offset": 0,
    }


def test_the_run_samples_on_the_distilled_model_and_trims_the_images_latent_before_decoding():
    payload = _payload(steps=6, cfg=1.0, shift=8.0, lora=NO_LORA)
    assert payload["4"] == {"class_type": "UNETLoader",
                            "inputs": {"unet_name": _params()["unet"], "weight_dtype": "default"}}
    assert payload["5"] == {"class_type": "LoraLoaderModelOnly",
                            "inputs": {"model": ["4", 0], "lora_name": DISTILL_LORA, "strength_model": 1.0}}
    assert payload["7"] == {"class_type": "ModelSamplingSD3", "inputs": {"model": ["5", 0], "shift": 8.0}}
    animate_id, _ = _node(payload, "WanAnimateToVideo")
    sampler_id, sampler = _node(payload, "KSampler")
    assert sampler["inputs"] == {
        "model": ["7", 0], "positive": [animate_id, 0], "negative": [animate_id, 1],
        "latent_image": [animate_id, 2], "seed": 5, "steps": 6, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }
    trim_id, trim = _node(payload, "TrimVideoLatent")
    assert trim["inputs"] == {"samples": [sampler_id, 0], "trim_amount": [animate_id, 3]}
    _decode_id, decode = _node(payload, "VAEDecode")
    assert decode["inputs"] == {"samples": [trim_id, 0], "vae": ["2", 0]}


def test_a_lora_of_the_users_own_goes_on_over_the_distilled_model():
    payload = _payload(lora="a_wan_lora.safetensors", lora_strength=0.7)
    assert payload["6"] == {"class_type": "LoraLoaderModelOnly",
                            "inputs": {"model": ["5", 0], "lora_name": "a_wan_lora.safetensors",
                                       "strength_model": 0.7}}
    assert payload["7"]["inputs"]["model"] == ["6", 0]


def test_the_video_is_written_with_the_library_videos_own_sound_at_the_playback_rate():
    payload = _payload(frame_rate=32.0)
    loader_id, _ = _node(payload, "VHS_LoadVideoPath")
    decode_id, _ = _node(payload, "VAEDecode")
    interpolate_id, interpolate = _node(payload, "RIFE VFI")
    assert interpolate["inputs"]["frames"] == [decode_id, 0]
    writer = payload[Wan22AnimateWorkflow.output_node_id]
    assert writer["class_type"] == "VHS_VideoCombine"
    assert writer["inputs"]["images"] == [interpolate_id, 0]
    assert writer["inputs"]["audio"] == [loader_id, 2]
    assert writer["inputs"]["frame_rate"] == 32.0
    assert writer["inputs"]["filename_prefix"] == "video/wan22_animate"


def test_a_clip_longer_than_one_window_goes_on_from_the_seam_frame_further_into_the_same_video():
    payload = _payload(frame_count=321)
    _loader_id, loader = _node(payload, "VHS_LoadVideoPath")
    assert loader["inputs"]["frame_load_cap"] == 321
    segments = dict(_nodes(payload, "WanAnimateToVideo"))
    assert set(segments) == {"19", "s1_animate"}   # 161 frames, then 160 more past the seam
    first, second = segments["19"], segments["s1_animate"]
    assert "continue_motion" not in first["inputs"]
    assert (first["inputs"]["length"], first["inputs"]["video_frame_offset"]) == (161, 0)
    assert second["inputs"]["continue_motion"] == ["s1_last", 0]
    assert (second["inputs"]["length"], second["inputs"]["video_frame_offset"]) == (161, 161)
    for segment in (first, second):
        assert segment["inputs"]["pose_video"] == first["inputs"]["pose_video"]
        assert segment["inputs"]["face_video"] == first["inputs"]["face_video"]
        assert segment["inputs"]["continue_motion_max_frames"] == 1


def test_the_run_is_cut_to_what_the_video_has_past_its_start(monkeypatch):
    monkeypatch.setattr(animate, "video_duration_seconds", lambda path: 4.0)
    payload = _payload(video_start=1.0, frame_count=81)
    _loader_id, loader = _node(payload, "VHS_LoadVideoPath")
    assert loader["inputs"]["skip_first_frames"] == 16
    assert loader["inputs"]["frame_load_cap"] == 45
    _animate_id, node = _node(payload, "WanAnimateToVideo")
    assert node["inputs"]["length"] == 45


def _library(tmp_path, monkeypatch) -> tuple[Path, Path]:
    videos = tmp_path / "videos" / "videos"
    scripts = tmp_path / "videos" / "scripts" / "scripts"
    monkeypatch.setattr(config, "LIBRARY_VIDEOS_DIR", videos)
    monkeypatch.setattr(config, "LIBRARY_SCRIPTS_DIR", scripts)
    return videos, scripts


_SCRIPT = [{"at": 0, "pos": 0}, {"at": 1500, "pos": 100}, {"at": 3000, "pos": 0},
           {"at": 4500, "pos": 100}, {"at": 6000, "pos": 0}, {"at": 7500, "pos": 100}]


def test_the_script_is_the_library_videos_cut_to_the_stretch_performed(tmp_path, monkeypatch):
    videos, scripts = _library(tmp_path, monkeypatch)
    video = videos / "2D" / "sample" / "scene one.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    write_funscript(scripts / "2D" / "sample" / "scene one.funscript", _SCRIPT)
    monkeypatch.setattr(animate, "video_duration_seconds", lambda path: 60.0)

    actions = Wan22AnimateWorkflow().authored_actions(_params(video=str(video), video_start=1.0, frame_count=81))

    assert actions == driven_actions(_SCRIPT, start_ms=1000, length_ms=5062)
    assert actions[0] == {"at": 0, "pos": 67}
    assert actions[-1] == {"at": 5062, "pos": 4}


def test_the_script_is_cut_to_what_the_video_has_when_the_run_is(tmp_path, monkeypatch):
    videos, scripts = _library(tmp_path, monkeypatch)
    video = videos / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    write_funscript(scripts / "clip.funscript", _SCRIPT)
    monkeypatch.setattr(animate, "video_duration_seconds", lambda path: 4.0)

    actions = Wan22AnimateWorkflow().authored_actions(_params(video=str(video), video_start=1.0, frame_count=81))

    assert actions[-1]["at"] == round(45 / NATIVE_FPS * 1000)


def test_a_video_with_no_script_leaves_the_script_to_the_metronome(tmp_path, monkeypatch):
    videos, _scripts = _library(tmp_path, monkeypatch)
    video = videos / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")

    assert Wan22AnimateWorkflow().authored_actions(_params(video=str(video))) is None
    assert Wan22AnimateWorkflow().authored_actions(_params(video="")) is None


def test_a_run_with_no_video_picked_has_nothing_to_start_from():
    wf = Wan22AnimateWorkflow()
    assert wf.missing_inputs(_params(video="")) == ["Video to Perform"]
    assert wf.missing_inputs(_params(input_image="")) == ["Image"]
    assert wf.missing_inputs(_params()) == []


def test_the_shown_size_is_derived_from_the_video_picked(monkeypatch):
    wf = Wan22AnimateWorkflow()
    monkeypatch.setattr(animate, "video_frame_size", lambda path: (1920, 1080))
    assert wf.derived_display_size(_params()) == scale_to_total_pixels(1920, 1080)
    monkeypatch.setattr(animate, "video_frame_size", lambda path: None)
    assert wf.derived_display_size(_params()) is None
    assert wf.derived_display_size(_params(video="")) is None


def test_the_form_offers_only_models_this_graph_can_run(monkeypatch):
    asked = {}

    def models(category, fallback, *, accepts, expert=None):
        asked[category] = accepts
        return list(fallback)

    def loras(fallback, *, accepts, expert=None):
        asked["loras"] = accepts
        return [NO_LORA, *fallback]

    monkeypatch.setattr(dropdowns, "list_model_files", models)
    monkeypatch.setattr("origenerator.workflows.lora_rows.list_lora_files", loras)
    by_key = {pd.key: pd for pd in Wan22AnimateWorkflow().param_definitions()}

    assert asked["diffusion_models"] == (WAN_ANIMATE,)
    assert asked["loras"] == (WAN,)
    assert by_key["unet"].type == "dropdown"
    assert by_key["video"].type == "video"
    assert by_key["video"].browse_dir == config.LIBRARY_VIDEOS_DIR
    assert by_key["input_image"].type == "image"
    assert by_key["video_start"].type == "float"
    assert [pd.key for pd in Wan22AnimateWorkflow().param_definitions()].index("unet") < \
        [pd.key for pd in Wan22AnimateWorkflow().param_definitions()].index("lora")


@pytest.mark.parametrize("missing", ["video", "input_image"])
def test_a_graph_still_builds_with_an_input_left_blank(missing):
    payload = _payload(**{missing: ""})
    assert payload[Wan22AnimateWorkflow.output_node_id]["class_type"] == "VHS_VideoCombine"
