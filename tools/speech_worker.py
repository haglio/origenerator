"""Speak lines with Qwen3-TTS, for Origenerator -- run by path, under the
Python of the environment Qwen3-TTS lives in, never imported by the app.

    python speech_worker.py job.json

The job names the voice (a preset speaker, or a recording to copy and what it
says), the seed, the device, the two model names, and the lines: each with the
seconds its scene runs, which is exactly how long its file comes out -- the
words, then silence to the end, so the mouth that follows this audio closes
when the line is done rather than mouthing on. A line longer than its scene is
cut at the scene's end; the log says so.

Only :func:`fit_to_seconds` is imported by the app's tests; everything heavy
is imported inside :func:`main`, so this file loads anywhere.
"""

from __future__ import annotations

import json
import sys
import time


def fit_to_seconds(wave, rate: int, seconds: float):
    """``wave`` padded with silence, or cut, to exactly ``seconds`` at ``rate``."""
    import numpy as np

    wanted = int(round(seconds * rate))
    wave = np.asarray(wave, dtype=np.float32).reshape(-1)
    if len(wave) >= wanted:
        return wave[:wanted]
    return np.concatenate([wave, np.zeros(wanted - len(wave), dtype=np.float32)])


def _load(model_name: str, device: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    try:
        return Qwen3TTSModel.from_pretrained(model_name, device_map=device, dtype=torch.bfloat16)
    except torch.cuda.OutOfMemoryError:
        print("no room on the GPU; speaking on the CPU", flush=True)
        return Qwen3TTSModel.from_pretrained(model_name, device_map="cpu", dtype=torch.float32)


def main(job_path: str) -> int:
    import soundfile as sf
    import torch

    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    voice = job["voice"]
    clone = voice["mode"] == "clone"
    started = time.time()
    model = _load(job["models"]["clone" if clone else "preset"], job.get("device", "cuda"))
    print(f"loaded in {time.time() - started:.0f}s", flush=True)
    prompt = None
    if clone:
        sample_text = voice.get("sample_text") or None
        prompt = model.create_voice_clone_prompt(
            ref_audio=voice["sample"], ref_text=sample_text,
            x_vector_only_mode=sample_text is None)
    for item in job["items"]:
        torch.manual_seed(int(job.get("seed") or 0))
        started = time.time()
        if clone:
            wavs, rate = model.generate_voice_clone(text=item["text"], voice_clone_prompt=prompt)
        else:
            wavs, rate = model.generate_custom_voice(text=item["text"], speaker=voice["speaker"])
        spoken = len(wavs[0]) / rate
        if spoken > item["seconds"]:
            print(f"cut: {spoken:.1f}s of words for a {item['seconds']:.1f}s scene", flush=True)
        sf.write(item["out"], fit_to_seconds(wavs[0], rate, item["seconds"]), rate)
        print(f"{spoken:.1f}s spoken in {time.time() - started:.0f}s -> {item['out']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
