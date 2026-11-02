"""Speak lines with Qwen3-TTS, for Origenerator: run by path under the Python of the environment pip installed it into,
never imported by the app (the tests import only fit_to_seconds).

    python speech_worker.py job.json
"""

from __future__ import annotations

import json
import sys
import time


def fit_to_seconds(wave, rate: int, seconds: float):
    import numpy as np  # noqa: PLC0415

    wanted = round(seconds * rate)
    wave = np.asarray(wave, dtype=np.float32).reshape(-1)
    if len(wave) >= wanted:
        return wave[:wanted]
    return np.concatenate([wave, np.zeros(wanted - len(wave), dtype=np.float32)])


def _load(model_name: str, device: str):
    import torch  # noqa: PLC0415
    from qwen_tts import Qwen3TTSModel  # noqa: PLC0415

    try:
        return Qwen3TTSModel.from_pretrained(model_name, device_map=device, dtype=torch.bfloat16)
    except torch.cuda.OutOfMemoryError:
        print("no room on the GPU; speaking on the CPU", flush=True)
        return Qwen3TTSModel.from_pretrained(model_name, device_map="cpu", dtype=torch.float32)


def main(job_path: str) -> int:
    import soundfile as sf  # noqa: PLC0415
    import torch  # noqa: PLC0415

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
            wavs, rate = model.generate_voice_clone(
                text=item["text"], language="Auto", voice_clone_prompt=prompt)
        else:
            wavs, rate = model.generate_custom_voice(
                text=item["text"], language="Auto", speaker=voice["speaker"])
        spoken = len(wavs[0]) / rate
        if spoken > item["seconds"]:
            print(f"cut: {spoken:.1f}s of words for a {item['seconds']:.1f}s scene", flush=True)
        sf.write(item["out"], fit_to_seconds(wavs[0], rate, item["seconds"]), rate)
        print(f"{spoken:.1f}s spoken in {time.time() - started:.0f}s -> {item['out']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
