"""Her lines, spoken: each scene's line of a story made into audio ComfyUI can
load, before the video that moves her lips to it is submitted.

A story's scenes carry ``scene_lines`` beside their prompts (see
:mod:`origenerator.gui.scenes_editor`). A scene with a line renders on WAN 2.2's
speech-to-video model, which reads the line as audio, so the audio has to exist
first: this module says which files a recipe needs and makes the ones missing.

The voice is Qwen3-TTS, run by ``tools/speech_worker.py`` in a Python
environment of its own -- its pins would break the app's and ComfyUI's -- named
by ``speech_python`` in the overlay. A line's file is named from everything that
shapes it (the words, the voice, the seed, the scene's length), so re-running a
recipe finds its lines already made, and a changed word or voice makes new ones.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# The CustomVoice model's preset speakers, the women first; the first is the
# default. A preset is the same voice every run, which a story needs across
# its scenes.
VOICE_PRESETS = ("Vivian", "Serena", "Ono_Anna", "Sohee", "Ryan", "Aiden",
                 "Uncle_Fu", "Dylan", "Eric")
# The Voice dropdown's last entry: not a preset but a recording of the user's
# own, named in the Voice Sample field, copied by the Base model.
CUSTOM_VOICE = "Custom voice (a recording)"
VOICE_OPTIONS = (*VOICE_PRESETS, CUSTOM_VOICE)
# Which of the family speaks: the presets, or a voice copied from a recording.
PRESET_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
CLONE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
# Where the lines land, under ComfyUI's input folder, which is where its
# LoadAudio reads from.
SPEECH_DIR = "origenerator_speech"
# The script that does the speaking: a plain file under tools/, run by path
# under the speech environment's Python. It imports nothing of this package,
# and lives outside it so the package's own dependency gate (which installs
# exactly what pyproject declares) never asks the app to carry the voice's
# torch.
WORKER = Path(__file__).resolve().parents[1] / "tools" / "speech_worker.py"
# Suppress the console-window flash Windows shows for a bare subprocess.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_STDERR_TAIL = 2000


class SpeechError(RuntimeError):
    """A line could not be spoken; the message says why, for the row's error."""


@dataclass(frozen=True)
class SceneSpeech:
    """One scene's line and the file that speaks it for the scene's length."""

    text: str
    frames: int
    file: str  # relative to ComfyUI's input folder, the way LoadAudio names it

    @property
    def seconds(self) -> float:
        # Imported here, not above: the workflows package imports this module
        # (its graphs read which scenes speak), so this module cannot import
        # the package back at load.
        from origenerator.workflows.frame_rate import NATIVE_FPS

        return self.frames / NATIVE_FPS


def voice_request(params: dict) -> dict:
    """Whose voice the lines are spoken in: the recording the recipe names when
    its Voice is the custom one (with what the recording says, which makes the
    copy a close one), else the preset speaker the Voice names."""
    voice = str(params.get("voice") or VOICE_PRESETS[0])
    if voice == CUSTOM_VOICE:
        return {"mode": "clone", "sample": str(params.get("voice_sample") or "").strip(),
                "sample_text": str(params.get("voice_sample_text") or "").strip()}
    return {"mode": "preset", "speaker": voice}


def scene_speech(params: dict) -> list[SceneSpeech | None]:
    """What each scene says, or ``None`` for a scene with no line.

    The scenes are ``scene_frames``, one length each; a lone scene is the whole
    clip and runs for ``frame_count`` -- the same reading of a recipe the graph's
    scene plan makes, so line and segment agree on the seconds. A recipe with
    no ``scene_lines`` at all is a workflow that cannot speak: no scenes.
    """
    if "scene_lines" not in params:
        return []
    frames = [int(n) for n in (params.get("scene_frames") or [])]
    if len(frames) < 2:
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
        shape = json.dumps([text, voice, seed, count], sort_keys=True)
        digest = hashlib.sha1(shape.encode("utf-8")).hexdigest()[:20]
        spoken.append(SceneSpeech(text, count, f"{SPEECH_DIR}/{digest}.wav"))
    return spoken


def missing_speech(params: dict, input_dir: Path) -> list[SceneSpeech]:
    """The lines whose files are not under ``input_dir`` yet."""
    return [scene for scene in scene_speech(params)
            if scene is not None and not (input_dir / scene.file).exists()]


def ensure_speech_files(params: dict, *, input_dir: Path, python: Path | None,
                        worker: Path | None = None, run=subprocess.run,
                        device: str = "cuda") -> list[Path]:
    """Speak every line of ``params`` that has no file yet, and return the files
    made. Raises :class:`SpeechError` when the voice is not set up or a line
    came back unspoken, with the worker's own words for why."""
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
