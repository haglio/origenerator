from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

VOICE_PRESETS = ("Vivian", "Serena", "Ono_Anna", "Sohee", "Ryan", "Aiden",
                 "Uncle_Fu", "Dylan", "Eric")
CUSTOM_VOICE = "Custom voice (a recording)"
VOICE_OPTIONS = (*VOICE_PRESETS, CUSTOM_VOICE)
PRESET_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
CLONE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
# Under ComfyUI's input folder, which is where its LoadAudio reads from.
SPEECH_DIR = "origenerator_speech"
# Run by path under the speech environment's Python; it lives outside the package
# so the dependency gate never asks the app to carry the voice's torch.
WORKER = Path(__file__).resolve().parents[1] / "tools" / "speech_worker.py"
SPEECH_VERSION = 2
# Windows flashes a console window for a bare subprocess.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_STDERR_TAIL = 2000


class SpeechError(RuntimeError): ...


@dataclass(frozen=True)
class SceneSpeech:
    text: str
    frames: int
    file: str  # relative to ComfyUI's input folder, the way LoadAudio names it

    @property
    def seconds(self) -> float:
        # Imported here: the workflows package imports this module at load.
        from origenerator.workflows.frame_rate import NATIVE_FPS  # noqa: PLC0415

        return self.frames / NATIVE_FPS


def voice_request(params: dict) -> dict:
    voice = str(params.get("voice") or VOICE_PRESETS[0])
    if voice == CUSTOM_VOICE:
        return {"mode": "clone", "sample": str(params.get("voice_sample") or "").strip(),
                "sample_text": str(params.get("voice_sample_text") or "").strip()}
    return {"mode": "preset", "speaker": voice}


def scene_speech(params: dict, *, version: int = SPEECH_VERSION) -> list[SceneSpeech | None]:
    if "scene_lines" not in params:
        return []
    frames = [int(n) for n in (params.get("scene_frames") or [])]
    if len(frames) <= 1:
        frames = [int(params["frame_count"])]
    lines = list(params.get("scene_lines") or [])
    voice = voice_request(params)
    seed = int(params.get("audio_seed") or 0)
    spoken: list[SceneSpeech | None] = []
    for index, count in enumerate(frames):
        text = str(lines[index] if index < len(lines) else "").strip()
        if not text:
            spoken.append(None)
            continue
        shape = json.dumps([version, text, voice, seed, count], sort_keys=True)
        digest = hashlib.sha1(shape.encode("utf-8")).hexdigest()[:20]
        spoken.append(SceneSpeech(text, count, f"{SPEECH_DIR}/{digest}.wav"))
    return spoken


def missing_speech(params: dict, input_dir: Path) -> list[SceneSpeech]:
    return [scene for scene in scene_speech(params)
            if scene is not None and not (input_dir / scene.file).exists()]


def ensure_speech_files(params: dict, *, input_dir: Path, python: Path | None,
                        worker: Path | None = None, run=subprocess.run,
                        device: str = "cuda") -> list[Path]:
    worker = worker or WORKER
    missing = missing_speech(params, input_dir)
    if not missing:
        return []
    if python is None:
        raise SpeechError(
            "No voice is set up: content.local.json names no speech_python, the "
            "Python of the environment Qwen3-TTS is installed in.")
    voice = voice_request(params)
    if voice["mode"] == "clone" and not voice["sample"]:
        raise SpeechError("The Voice is a custom recording, but Voice Sample names no file.")
    if voice["mode"] == "clone" and not Path(voice["sample"]).is_file():
        raise SpeechError(f"The Voice Sample is not a file: {voice['sample']}")
    speech_dir = input_dir / SPEECH_DIR
    speech_dir.mkdir(parents=True, exist_ok=True)
    job = {
        "device": device,
        "seed": int(params.get("audio_seed") or 0),
        "voice": voice,
        "models": {"preset": PRESET_MODEL, "clone": CLONE_MODEL},
        "items": [{"text": scene.text, "seconds": scene.seconds,
                   "out": str(input_dir / scene.file)} for scene in missing],
    }
    job_path = speech_dir / f"job_{missing[0].file.rsplit('/', 1)[-1][:-4]}.json"
    job_path.write_text(json.dumps(job, indent=1), encoding="utf-8")
    logger.info("Speaking %d line(s) with %s", len(missing), python)
    try:
        result = run([str(python), str(worker), str(job_path)],
                     capture_output=True, text=True, creationflags=_NO_WINDOW)
    finally:
        job_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise SpeechError(
            f"The voice failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()[-_STDERR_TAIL:]}")
    unspoken = [scene.file for scene in missing if not (input_dir / scene.file).exists()]
    if unspoken:
        raise SpeechError(f"The voice wrote nothing for: {', '.join(unspoken)}")
    return [input_dir / scene.file for scene in missing]
