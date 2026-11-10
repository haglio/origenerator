from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from origenerator import config
from origenerator.base_models import made_for_text_to_video
from origenerator.model_titles import MODEL_EXTENSIONS, fix_of, is_a_fixs_lora, model_title
from origenerator.workflows import model_arch

# The directory the Impact Subpack's ``UltralyticsDetectorProvider`` scans, where the enhance graph's detail pass
# finds its face/hand detectors in ComfyUI.
_DETECTOR_CATEGORY = "ultralytics/bbox"
# ComfyUI hands out a part's outline only for a model in its segm folder; the same file under bbox gives boxes alone.
_OUTLINE_DETECTOR_CATEGORY = "ultralytics/segm"

NO_LORA = "None"

ANY = "any"
WORKS_ON_PIXELS = ANY
_NO_FALLBACK: list[str] = []


def _model_paths(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [f for f in directory.rglob("*") if f.is_file() and f.suffix in MODEL_EXTENSIONS]


_catalogued: dict[str, tuple[tuple, list[tuple[str, model_arch.ModelFile]]]] = {}


def _folder_stamp(directory: Path) -> tuple:
    return tuple((root, os.stat(root).st_mtime_ns, len(dirs) + len(files))
                 for root, dirs, files in os.walk(directory))


def _catalogue(directory: Path) -> list[tuple[str, model_arch.ModelFile]]:
    stamp = _folder_stamp(directory)
    kept = _catalogued.get(str(directory))
    if kept is None or kept[0] != stamp:
        kept = (stamp, [(_as_comfyui_names_it(path, directory), model_arch.describe(path))
                        for path in _model_paths(directory)])
        _catalogued[str(directory)] = kept
    return kept[1]


def _as_comfyui_names_it(path: Path, directory: Path) -> str:
    return str(path.relative_to(directory))


def _offer(described: model_arch.ModelFile, accepts, expert: str | None,
           want_lora: bool) -> bool:
    if described.is_shard:
        return False
    if described.is_lora != want_lora:
        return False
    if _is_surely_another_family(described, accepts):
        return False
    return not _names_the_other_expert(described, expert)


def _is_surely_another_family(described: model_arch.ModelFile, accepts) -> bool:
    return accepts != ANY and described.arch is not None and described.arch not in accepts


def _names_the_other_expert(described: model_arch.ModelFile, expert: str | None) -> bool:
    return bool(expert and described.expert and described.expert != expert)


def _as_civitai_files_it(name: str, described: model_arch.ModelFile) -> model_arch.ModelFile:
    if described.is_lora and described.arch == model_arch.WAN and made_for_text_to_video(name):
        return replace(described, arch=model_arch.WAN_T2V)
    return described


def _listing(category: str, fallback: list[str], accepts, expert, want_lora) -> list[str]:
    directory = config.COMFYUI_DIR / "models" / category
    found = sorted((name for name, described in _catalogue(directory)
                    if _offer(_as_civitai_files_it(name, described), accepts, expert, want_lora)),
                   key=lambda name: (model_title(name).casefold(), name))
    return found or list(fallback)


def list_model_files(
    category: str, fallback: list[str], *, accepts, expert: str | None = None,
) -> list[str]:
    return _listing(category, fallback, accepts, expert, want_lora=False)


def list_lora_files(
    fallback: list[str], *, accepts, expert: str | None = None, fix: str | None = "",
) -> list[str]:
    listing = _listing("loras", fallback, accepts, expert, want_lora=True)
    return [NO_LORA, *(name for name in listing if not is_no_lora(name)
                       and (fix is None or not is_a_fixs_lora(name) or fix_of(name) == fix))]


def list_detector_files() -> list[str]:
    return list_model_files(_DETECTOR_CATEGORY, _NO_FALLBACK,
                            accepts=WORKS_ON_PIXELS)


def list_outline_detector_files() -> list[str]:
    return list_model_files(_OUTLINE_DETECTOR_CATEGORY, _NO_FALLBACK,
                            accepts=WORKS_ON_PIXELS)


def is_installed(folder: str, value) -> bool:
    return bool(folder) and (config.COMFYUI_DIR / "models" / folder / str(value)).is_file()


def is_no_lora(value) -> bool:
    return not value or value == NO_LORA
