from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from app_support.comfy_file_refs import reference_basename

from origenerator import config, precision
from origenerator.precision import Precision
from origenerator.workflows.model_arch import describe, safetensors_metadata

_QUANTIZED_FLUX_SUFFIX = ".gguf"
MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", _QUANTIZED_FLUX_SUFFIX, ".sft")
_TRAINED_AT = ("ss_training_finished_at", "ss_training_started_at")
FIX_LORA_FOLDER = "fixes"
_FIX_LORA = re.compile(r"^(?P<part>.+) (?P<when>\d{4}-\d{2}-\d{2} \d{4})$")
_VERSIONED = re.compile(r"^(?P<base>.+?) (?P<major>\d+)\.(?P<minor>\d+)$")
_FOLDERS_SHOWN_BY_TITLE = ("diffusion_models", "checkpoints", "loras")
_read: dict[str, tuple[tuple[int, int], object]] = {}


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


def versioned(title: str) -> tuple[str, Version] | None:
    found = _VERSIONED.match(title)
    if found is None:
        return None
    return found["base"], Version(int(found["major"]), int(found["minor"]))


def model_stem(value) -> str:
    name = reference_basename(str(value))
    for extension in MODEL_EXTENSIONS:
        if name.lower().endswith(extension):
            return name[: -len(extension)]
    return name


def option_title(option) -> str:
    return model_title(option) if str(option).lower().endswith(MODEL_EXTENSIONS) else str(option)


def model_title(value) -> str:
    title = _kept_title(value)
    shown = _precision_shown(value, title)
    return title if shown is None else precision.in_plain_words(title, shown)


def precision_help(value) -> str:
    shown = _precision_shown(value, _kept_title(value))
    if shown is None:
        return ""
    installed = _installed(value)
    size = "" if installed is None else precision.file_size_sentence(installed.stat().st_size)
    return " ".join(filter(None, (shown.explained(), size)))


def _kept_title(value) -> str:
    stem = model_stem(value)
    return kept_by_stem(config.MODEL_TITLES_PATH).get(stem) or _fix_title(value, stem) or stem


def _precision_shown(value, title: str) -> Precision | None:
    named = precision.named_in(title)
    if named is None:
        return None
    installed = _installed(value)
    inside = None if installed is None else describe(installed).precision
    return precision.tagged(inside) or named


def _installed(value) -> Path | None:
    for folder in _FOLDERS_SHOWN_BY_TITLE:
        path = config.COMFYUI_DIR / "models" / folder / str(value)
        if path.is_file():
            return path
    return None


def is_a_fixs_lora(value) -> bool:
    return PurePosixPath(str(value).replace("\\", "/")).parent.name == FIX_LORA_FOLDER


def fix_of(value) -> str | None:
    if not is_a_fixs_lora(value):
        return None
    stem = model_stem(value)
    by_version = versioned(stem)
    if by_version is not None:
        return by_version[0]
    fix = _FIX_LORA.match(stem)
    return None if fix is None else fix["part"]


def _fix_title(value, stem: str) -> str | None:
    if not is_a_fixs_lora(value):
        return None
    by_version = versioned(stem)
    if by_version is not None:
        part, version = by_version
        return f"{part.capitalize()} fix {version}"
    fix = _FIX_LORA.match(stem)
    if fix is None:
        return None
    return f"{fix['part'].capitalize()} fix {Version(1, _dated_fix_rank(fix['part'], stem))}"


def lora_folder():
    return config.COMFYUI_DIR / "models" / "loras"


def _dated_fix_rank(part: str, stem: str) -> int:
    try:
        stems = [path.stem for path in (lora_folder() / FIX_LORA_FOLDER).iterdir()]
    except OSError:
        return 0
    return sum(1 for other in stems
               if (dated := _FIX_LORA.match(other)) and dated["part"] == part and other < stem)


def kept_by_stem(path) -> dict:
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        kept = _read.get(str(path))
        if kept is None or kept[0] != stamp:
            kept = _read[str(path)] = (stamp, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return kept[1] if isinstance(kept[1], dict) else {}


def write_kept(path, entries: dict) -> None:
    every = {**kept_by_stem(path), **entries}
    path.write_text(json.dumps(every, sort_keys=True, indent=1), encoding="utf-8")


def write_title(stem: str, title: str) -> None:
    write_kept(config.MODEL_TITLES_PATH, {stem: title})


def trained_when(path) -> datetime | None:
    metadata = safetensors_metadata(path)
    for key in _TRAINED_AT:
        try:
            return datetime.fromtimestamp(float(metadata[key])).astimezone()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    return None


def trained_sentence(lora) -> str:
    if versioned(model_title(lora)) is None:
        return ""
    when = trained_when(lora_folder() / str(lora))
    return f"Trained {when:%Y-%m-%d %H:%M}." if when is not None else ""
