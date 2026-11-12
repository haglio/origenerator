from __future__ import annotations

from origenerator.workflows.frame_rate import playback_rate

BITRATE_MEGABITS = 20

VIDEO_WRITER = "VHS_VideoCombine"


def video_writer(frames_ref, audio_ref, params: dict) -> dict:
    return {
        "class_type": VIDEO_WRITER,
        "inputs": {
            "images": frames_ref,
            **({"audio": audio_ref} if audio_ref is not None else {}),
            "frame_rate": playback_rate(params["frame_rate"]),
            "loop_count": 0,
            "filename_prefix": params["filename_prefix"],
            "format": "video/nvenc_h264-mp4",
            "pix_fmt": "yuv420p",
            "bitrate": BITRATE_MEGABITS,
            "megabit": True,
            "save_metadata": True,
            "trim_to_audio": False,
            "pingpong": False,
            "save_output": True,
        },
    }
