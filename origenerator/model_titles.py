from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import PurePosixPath

from origenerator import config
from origenerator.file_refs import reference_basename

MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft")
FIX_LORA_FOLDER = "fixes"
_FIX_LORA_STAMP = "%Y-%m-%d %H%M"
_FIX_LORA = re.compile(r"^(?P<part>.+) (?P<when>\d{4}-\d{2}-\d{2} \d{4})$")
_read: dict[str, tuple[tuple[int, int], object]] = {}


def _stem(value) -> str:
    name = reference_basename(str(value))
    for extension in MODEL_EXTENSIONS:
        if name.lower().endswith(extension):
            return name[: -len(extension)]
    return name


def fix_lora_name(part: str, when: datetime) -> str:
    return f"{part} {when.strftime(_FIX_LORA_STAMP)}"


def option_title(option) -> str:
    return model_title(option) if str(option).lower().endswith(MODEL_EXTENSIONS) else str(option)


def model_title(value) -> str:
    stem = _stem(value)
    return _titles().get(stem) or _fix_title(value, stem) or stem


def _fix_title(value, stem: str) -> str | None:
    folder = PurePosixPath(str(value).replace("\\", "/")).parent.name
    fix = _FIX_LORA.match(stem) if folder == FIX_LORA_FOLDER else None
    if fix is None:
        return None
    when = datetime.strptime(fix["when"], _FIX_LORA_STAMP)
    return f"{fix['part'].capitalize()} fix ({when:%Y-%m-%d %H:%M})"


def _titles() -> dict[str, str]:
    path = config.MODEL_TITLES_PATH
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        kept = _read.get(str(path))
        if kept is None or kept[0] != stamp:
            kept = _read[str(path)] = (stamp, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return kept[1] if isinstance(kept[1], dict) else {}
