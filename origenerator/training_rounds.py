from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator import card_claim

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".bmp", ".tif", ".tiff"})
IDLE_CHECKS = 6
IDLE_CHECK_SECONDS = 20
GRAPHICS_CARD_FREE_MIB = 3000
POLL_SECONDS = 5
ROUNDS = 12
_STEPS = re.compile(rb"steps:\s+\d+%\|[^|]*\|\s*(\d+)/(\d+)")
_MEMORY_RAN_OUT = (b"OutOfMemoryError", b"CUDA out of memory", b"CUDA error: out of memory")
RAN_OUT_OF_MEMORY = ("The graphics card ran out of memory while training. Close anything else "
                     "using it, then press Train again.")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IN_THE_BACKGROUND = NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


class Stopped(Exception):
    pass


def status(job: dict, **fields) -> None:
    Path(job["status"]).write_text(json.dumps(fields), encoding="utf-8")


def said_why(job: dict) -> bool:
    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))["state"] == "failed"
    except (OSError, ValueError, KeyError):
        return False


def let_go_of_the_graphics_card() -> None:
    card_claim.release(os.getpid())


def ran_out_of_memory(said: bytes) -> bool:
    return any(sign in said for sign in _MEMORY_RAN_OUT)


class Machine:
    def __init__(self, comfyui: str, holder: str = ""):
        self._comfyui = comfyui
        self._holder = holder

    def graphics_card_held_by_another(self) -> bool:
        return card_claim.held_by_another(os.getpid())

    def claim_graphics_card(self) -> bool:
        return card_claim.take(self._holder, os.getpid())

    def release_graphics_card(self) -> None:
        let_go_of_the_graphics_card()

    def jobs_waiting(self) -> int | None:
        try:
            with urllib.request.urlopen(f"{self._comfyui}/prompt", timeout=5) as answer:
                return int(json.load(answer)["exec_info"]["queue_remaining"])
        except Exception:
            return None

    def unload_comfyui(self) -> None:
        request = urllib.request.Request(
            f"{self._comfyui}/free", method="POST",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except Exception:
            return
        time.sleep(5)

    def graphics_card_memory_mib(self) -> int | None:
        try:
            said = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=30,
                                  creationflags=NO_WINDOW, check=False).stdout
            return int(said.strip().splitlines()[0])
        except Exception:
            return None

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def machine_of(job: dict) -> Machine:
    return Machine(job["comfyui"], f"{job['display_name']} training")


def wait_for_idle(job: dict, machine) -> None:
    status(job, state="waiting")
    while True:
        quiet = 0
        while quiet < IDLE_CHECKS:
            free = machine.jobs_waiting() in (0, None) and not machine.graphics_card_held_by_another()
            quiet = quiet + 1 if free else 0
            machine.sleep(IDLE_CHECK_SECONDS)
        memory = machine.graphics_card_memory_mib()
        if memory is not None and memory >= GRAPHICS_CARD_FREE_MIB:
            machine.unload_comfyui()
            machine.sleep(10)
            memory = machine.graphics_card_memory_mib()
        if memory is not None and memory >= GRAPHICS_CARD_FREE_MIB:
            print(f"== the graphics card still holds {memory} MiB with ComfyUI's line empty; waiting on",
                  flush=True)
        elif machine.claim_graphics_card():
            return
        else:
            print("== another trainer took the graphics card first; waiting on", flush=True)
        machine.sleep(60)


def output_folder(job: dict) -> Path:
    return Path(job["work"]) / "output"


def _steps_done_file(job: dict) -> Path:
    return Path(job["work"]) / "steps_done.txt"


def _newest_state(output: Path) -> Path | None:
    states = [path for path in output.glob("*-state") if path.is_dir()]
    return max(states, key=lambda path: path.stat().st_mtime) if states else None


def _state_step(state: Path) -> int | None:
    found = re.search(r"-step(\d+)-state$", state.name)
    return int(found[1]) if found else None


def _tally(file: Path) -> int:
    try:
        return int(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0


class _Progress(threading.Thread):
    def __init__(self, process, job: dict, done: int):
        super().__init__(daemon=True)
        self._process, self._job, self._done = process, job, done
        self.tail = b""

    def run(self) -> None:
        while chunk := self._process.stdout.read1(256):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            self.tail = (self.tail + chunk)[-4096:]
            steps = _STEPS.findall(self.tail)
            if steps:
                status(self._job, state="training", done=self._done + int(steps[-1][0]),
                       total=self._job["steps"])


def end_process(process) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True,
                   creationflags=NO_WINDOW, check=False)


@dataclass(frozen=True)
class Rounds:
    command: Callable[[int, Path | None], list[str]]
    saved_states_count_every_round: bool = False


def train(job: dict, machine, rounds: Rounds, popen=subprocess.Popen, kill=end_process) -> None:
    output = output_folder(job)
    output.mkdir(parents=True, exist_ok=True)
    tally = _steps_done_file(job)
    crashes = 0
    while True:
        done = _tally(tally)
        remaining = job["steps"] - done
        if remaining <= 0:
            return
        wait_for_idle(job, machine)
        machine.unload_comfyui()
        resume = _newest_state(output)
        status(job, state="training", done=done, total=job["steps"])
        round_start = time.time()
        print(f"== training {remaining} more of {job['steps']} steps"
              + (f", resuming from {resume.name}" if resume is not None else ""), flush=True)
        process = popen(rounds.command(done, resume), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, creationflags=IN_THE_BACKGROUND)
        progress = _Progress(process, job, done)
        progress.start()
        stopped_for_comfyui = False
        while process.poll() is None:
            machine.sleep(POLL_SECONDS)
            if machine.jobs_waiting() not in (0, None):
                print("== ComfyUI has a job; stopping the trainer until the graphics card is idle again",
                      flush=True)
                kill(process)
                stopped_for_comfyui = True
                process.wait()
        progress.join()
        if process.returncode == 0 and not stopped_for_comfyui:
            tally.write_text(str(job["steps"]), encoding="utf-8")
            return
        newest = _newest_state(output)
        if (newest is not None and newest.stat().st_mtime >= round_start
                and (step := _state_step(newest)) is not None):
            done = done + step if rounds.saved_states_count_every_round else step
            tally.write_text(str(done), encoding="utf-8")
            print(f"== progress kept: {done} of {job['steps']} steps saved", flush=True)
        machine.release_graphics_card()
        if stopped_for_comfyui:
            machine.sleep(10)
            continue
        if ran_out_of_memory(progress.tail):
            raise Stopped(RAN_OUT_OF_MEMORY)
        crashes += 1
        if crashes >= ROUNDS:
            raise Stopped(f"The training program stopped {crashes} times. Nothing about your "
                          f"images caused it; an agent can read why in {job['log']}.")
        machine.sleep(60)


def install(job: dict, **said) -> None:
    made = output_folder(job) / f"{job['output_name']}.safetensors"
    if not made.is_file():
        raise Stopped("The training ended without a LoRA to install. An agent can read why in "
                      f"{job['log']}.")
    destination = Path(job["lora_folder"]) / made.name
    if destination.exists():
        raise Stopped(f"{destination} is there already, so nothing was installed over it. An "
                      "agent can sort out which training made it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(made, destination)
    Path(job["trained"]).write_text(
        json.dumps({"photo_stamps": job["image_stamps"], "lora": job["lora"]}), encoding="utf-8")
    shutil.rmtree(output_folder(job))
    _steps_done_file(job).unlink(missing_ok=True)
    status(job, state="done", lora=job["lora"], **said)


def main(argv: list[str], steps: dict, doing: dict) -> int:
    step, job_path = argv
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    os.environ.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        steps[step](job)
    except Stopped as stopped:
        if str(stopped):
            status(job, state="failed", message=str(stopped))
        return 1
    except Exception:
        traceback.print_exc()
        status(job, state="failed", message=f"The training stopped with an error while "
                                            f"{doing[step]}. An agent can read why in "
                                            f"{job['log']}.")
        return 1
    finally:
        let_go_of_the_graphics_card()
    return 0
