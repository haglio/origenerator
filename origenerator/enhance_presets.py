from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from app_support.file_channel import read_whole, write_whole

from origenerator.config import LIBRARY_STATE_DIR
from origenerator.gallery.enhance import most_used_enhancements
from origenerator.gallery.enhance_settings import describe_enhance_params, full_settings

logger = logging.getLogger(__name__)

PRESETS_PATH = LIBRARY_STATE_DIR / "enhance_presets.json"
STARTING_COUNT = 5


class Preset(NamedTuple):
    name: str
    params: dict


def load(rows_of_a_new_library: Callable[[], Iterable[dict]], *,
         path: Path | None = None) -> list[Preset]:
    path = path or PRESETS_PATH
    if path.exists():
        return _kept_in(path)
    return _keep([Preset(describe_enhance_params(settings), settings)
                  for settings in most_used_enhancements(rows_of_a_new_library(),
                                                         STARTING_COUNT)], path)


def save(name: str, params: dict, *, path: Path | None = None) -> list[Preset]:
    path = path or PRESETS_PATH
    return _keep([*_kept_in(path), Preset(name, dict(params))], path)


def rename(index: int, name: str, *, path: Path | None = None) -> list[Preset]:
    path = path or PRESETS_PATH
    return _keep([preset._replace(name=name) if at == index else preset
                  for at, preset in enumerate(_kept_in(path))], path)


def matching(presets: list[Preset], params: dict) -> int | None:
    wanted = full_settings(params)
    return next((at for at, preset in enumerate(presets)
                 if full_settings(preset.params) == wanted), None)


def _kept_in(path: Path) -> list[Preset]:
    try:
        return [Preset(str(held["name"]), dict(held["params"]))
                for held in json.loads(read_whole(path))["presets"]]
    except FileNotFoundError:
        return []
    except (ValueError, KeyError, TypeError) as unreadable:
        logger.warning("Enhance presets in %s unreadable (%s): starting none", path, unreadable)
        return []


def _keep(presets: list[Preset], path: Path) -> list[Preset]:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps({"presets": [preset._asdict() for preset in presets]},
                                 indent=2) + "\n")
    return presets
