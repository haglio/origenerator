from __future__ import annotations

from origenerator.workflows.frame_rate import playback_rate

CRF = 13


def video_writer(frames_ref, audio_ref, params: dict) -> dict:
    return {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "images": frames_ref,
            "audio": audio_ref,
            "frame_rate": playback_rate(params["frame_rate"]),
            "loop_count": 0,
            "filename_prefix": params["filename_prefix"],
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
            "crf": CRF,
            "save_metadata": True,
            "trim_to_audio": False,
            "pingpong": False,
            "save_output": True,
        },
    }
