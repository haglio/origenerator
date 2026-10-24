from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from origenerator.file_refs import OUTPUT_TAG, split_annotation
from origenerator.output_places import OutputPlaces

_NUMBERED = re.compile(r"^(?P<stem>.+)_(?P<counter>\d+)(?P<rest>\D*\.[^.]+)$")
READS = "reads"
ADD_ON_SCRATCH = frozenset({"VRGDG_TEMP"})
PICTURE_LOADERS = frozenset({"LoadImage", "LoadImageMask"})


@dataclass(frozen=True)
class HandedOver:
    payload: dict
    reads: tuple[tuple[Path, Path], ...]

    def copy_reads(self) -> None:
        for source, copy in self.reads:
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy)


def handed_to_comfyui(payload: dict, places: OutputPlaces, prompt_id: str) -> HandedOver:
    run = _run_subfolder(places, prompt_id)
    reads: list[tuple[Path, Path]] = []
    handed = {}
    for node_id, node in _saving_into_its_run_folder(payload, places, prompt_id).items():
        inputs = dict(node.get("inputs", {}))
        for key, value in inputs.items():
            source, named = _what_it_reads(node.get("class_type"), key, value, places, node_id)
            if source is not None and source.is_file():
                copied = f"{run}/{READS}/{named}"
                inputs[key] = f"{copied} {OUTPUT_TAG}"
                reads.append((source, places.comfyui / copied))
        handed[node_id] = {**node, "inputs": inputs} if "inputs" in node else node
    return HandedOver(handed, tuple(reads))


def _what_it_reads(class_type, key: str, value, places: OutputPlaces, node_id: str):
    if not isinstance(value, str):
        return None, ""
    named, tag = split_annotation(value)
    if tag == OUTPUT_TAG:
        return places.file(named), named.replace("\\", "/")
    picked = Path(named)
    if tag == "" and class_type in PICTURE_LOADERS and key == "image" and picked.is_absolute():
        return picked, f"picked/{node_id}/{picked.name}"
    return None, ""


def _saving_into_its_run_folder(payload: dict, places: OutputPlaces, prompt_id: str) -> dict:
    run = _run_subfolder(places, prompt_id)
    return {node_id: _saving_under(node, run) for node_id, node in payload.items()}


def _saving_under(node: dict, run: str) -> dict:
    prefix = node.get("inputs", {}).get("filename_prefix")
    if not isinstance(prefix, str):
        return node
    return {**node, "inputs": {**node["inputs"], "filename_prefix": f"{run}/{prefix}"}}


def file_into_library(files: list[dict], places: OutputPlaces, prompt_id: str) -> list[dict]:
    run = _run_subfolder(places, prompt_id)
    filed: dict[tuple[str, str], tuple[str, str]] = {}
    for record in files:
        subfolder, name = _key(record)
        if (subfolder, name) in filed or not subfolder.startswith(f"{run}/"):
            continue
        kind = subfolder.removeprefix(f"{run}/")
        moved = _file_with_its_numbered_siblings(places.comfyui / subfolder, name,
                                                 places.folder(kind))
        filed.update({(subfolder, was): (kind, now) for was, now in moved.items()})
    forget_the_runs_copies(places, prompt_id)
    return [_as_filed(record, filed) for record in files]


def file_what_comfyui_left(places: OutputPlaces, *, in_flight: set[str]) -> int:
    filed = 0
    for run in _folders_in(places.working):
        if run.name not in in_flight:
            forget_the_runs_copies(places, run.name)
            filed += _file_everything_under(run, run, places)
    if places.keeps_outputs_in_comfyuis_folder():
        return filed
    for top in _folders_in(places.comfyui):
        if top != places.working and top.name not in ADD_ON_SCRATCH:
            filed += _file_everything_under(top, places.comfyui, places)
    return filed


def _file_everything_under(top: Path, kinds_from: Path, places: OutputPlaces) -> int:
    filed = 0
    for folder, names in _walk_files(top):
        home = places.folder(folder.relative_to(kinds_from).as_posix())
        if home == folder:
            continue
        for name in names:
            if (folder / name).is_file():
                filed += len(_file_with_its_numbered_siblings(folder, name, home))
    _remove_what_is_left_empty(top)
    return filed


def _folders_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [child for child in sorted(folder.iterdir())
            if child.is_dir() and not os.path.isjunction(child)]


def _walk_files(top: Path):
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(name for name in dirnames
                             if not os.path.isjunction(os.path.join(dirpath, name)))
        yield Path(dirpath), sorted(filenames)


def forget_the_runs_copies(places: OutputPlaces, prompt_id: str) -> None:
    shutil.rmtree(places.run(prompt_id) / READS, ignore_errors=True)
    _remove_what_is_left_empty(places.run(prompt_id))


def _remove_what_is_left_empty(folder: Path) -> None:
    for dirpath, _dirnames, _filenames in os.walk(folder, topdown=False):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


def _run_subfolder(places: OutputPlaces, prompt_id: str) -> str:
    return places.run(prompt_id).relative_to(places.comfyui).as_posix()


def _file_with_its_numbered_siblings(waiting: Path, name: str, home: Path) -> dict[str, str]:
    match = _NUMBERED.match(name)
    if match is None:
        return {}
    siblings = [sibling for sibling in os.listdir(waiting)
                if (other := _NUMBERED.match(sibling))
                and (other["stem"], other["counter"]) == (match["stem"], match["counter"])]
    home.mkdir(parents=True, exist_ok=True)
    number = _next_number(home, match["stem"])
    filed_as = {sibling: _numbered(sibling, match["stem"], number) for sibling in siblings}
    for sibling, new_name in filed_as.items():
        os.rename(waiting / sibling, home / new_name)
    return filed_as


def _numbered(name: str, stem: str, number: int) -> str:
    return f"{stem}_{number:05}{_NUMBERED.match(name)['rest']}"


def _next_number(home: Path, stem: str) -> int:
    numbers = [int(match["counter"]) for name in os.listdir(home)
               if (match := _NUMBERED.match(name)) and match["stem"] == stem]
    return max(numbers, default=0) + 1


def _key(record: dict) -> tuple[str, str]:
    return (record.get("subfolder") or "").replace("\\", "/"), record.get("filename") or ""


def _as_filed(record: dict, filed: dict[tuple[str, str], tuple[str, str]]) -> dict:
    kind_and_name = filed.get(_key(record))
    if kind_and_name is None:
        return record
    kind, name = kind_and_name
    return {**record, "subfolder": kind, "filename": name}
