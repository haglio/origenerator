from __future__ import annotations

from origenerator.workflows.base import SizedInput
from origenerator.workflows.minimax_h3 import MiniMaxH3Workflow
from origenerator.workflows.model_arch import REF2VA


class MiniMaxH3Ref2vWorkflow(MiniMaxH3Workflow):
    """The prompt names the references as ``<Picture 1>``, ``<Video 1>`` and
    ``<Audio 1>``, counted per kind in the order they are given; Comfy's guide
    finds the four-step turbo barely applies them, so Turbo starts off here."""

    name = "minimax_h3_ref2v"
    version = "v001"
    display_name = "MiniMax H3 Reference-to-Video"
    mode = REF2VA
    checkpoint = "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors"
    turbo_lora = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    turbo = False
    steps = 20
    good_steps = (16, 25)
    picture_label = "Reference Picture"

    def own_defaults(self) -> dict:
        return {"ref_images": [], "ref_videos": [], "ref_audios": []}

    def conditioning_nodes(self, params: dict, sized: SizedInput) -> dict:
        inputs = {
            "clip": ["2", 0],
            "vae": ["3", 0],
            "audio_vae": ["7", 0],
            "prompt": params["positive_prompt"],
            "width": sized.width,
            "height": sized.height,
            "length": params["frame_count"],
            "ref_image_size": "match",
            "ref_images.ref_image_0": ["1", 0],
        }
        nodes = {}
        for index, picture in enumerate(params.get("ref_images") or (), start=1):
            node_id = f"ref_picture_{index}"
            nodes[node_id] = {"class_type": "LoadImage", "inputs": {"image": picture}}
            inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]
        for index, video in enumerate(params.get("ref_videos") or ()):
            node_id, parts_id = f"ref_video_{index}", f"ref_video_parts_{index}"
            nodes[node_id] = {"class_type": "LoadVideo", "inputs": {"file": video}}
            nodes[parts_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [node_id, 0]}}
            inputs[f"ref_videos.ref_video_{index}"] = [parts_id, 0]
            inputs[f"ref_video_audios.ref_video_audio_{index}"] = [parts_id, 1]
        for index, sound in enumerate(params.get("ref_audios") or ()):
            node_id = f"ref_sound_{index}"
            nodes[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": sound}}
            inputs[f"ref_audios.ref_audio_{index}"] = [node_id, 0]
        return {**nodes, **self.conditioning("MiniMaxH3ReferenceToVideo", inputs)}
