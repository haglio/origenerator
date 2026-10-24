from __future__ import annotations

import os
import re
from pathlib import Path

from origenerator.output_places import OutputPlaces, files_under, folders_in

_NUMBERED = re.compile(r"^(?P<stem>.+)_(?P<counter>\d+)(?P<rest>\D*\.[^.]+)$")
ADD_ON_SCRATCH = frozenset({"VRGDG_TEMP"})


def saving_into_its_run_folder(payload: dict, places: OutputPlaces, prompt_id: str) -> dict:
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
        moved = _file_into_its_home(places.comfyui / subfolder, name, places.folder(kind))
        filed.update({(subfolder, was): (kind, now) for was, now in moved.items()})
    _remove_what_is_left_empty(places.run(prompt_id))
    return [_as_filed(record, filed) for record in files]


def file_what_comfyui_left(places: OutputPlaces, *, in_flight: set[str]) -> int:
    filed = 0
    for run in folders_in(places.working):
        if run.name not in in_flight:
            filed += _file_everything_under(run, run, places)
    if places.keeps_outputs_in_comfyuis_folder():
        return filed
    for top in folders_in(places.comfyui):
        if top != places.working and top.name not in ADD_ON_SCRATCH:
            filed += _file_everything_under(top, places.comfyui, places)
    return filed


def _file_everything_under(top: Path, kinds_from: Path, places: OutputPlaces) -> int:
    filed = 0
    for folder, names in files_under(top):
        home = places.folder(folder.relative_to(kinds_from).as_posix())
        for name in names:
            if (folder / name).is_file():
                filed += len(_file_into_its_home(folder, name, home))
    _remove_what_is_left_empty(top)
    return filed


def _remove_what_is_left_empty(folder: Path) -> None:
    for dirpath, _dirnames, _filenames in os.walk(folder, topdown=False):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


def _run_subfolder(places: OutputPlaces, prompt_id: str) -> str:
    return places.run(prompt_id).relative_to(places.comfyui).as_posix()


def _file_into_its_home(waiting: Path, name: str, home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    filed_as = _names_in_its_home(waiting, name, home)
    for was, now in filed_as.items():
        os.rename(waiting / was, home / now)
    return filed_as


def _names_in_its_home(waiting: Path, name: str, home: Path) -> dict[str, str]:
    match = _NUMBERED.match(name)
    if match is None:
        return {} if os.path.lexists(home / name) else {name: name}
    number = _next_number(home, match["stem"])
    return {sibling: _numbered(sibling, match["stem"], number)
            for sibling in os.listdir(waiting)
            if (other := _NUMBERED.match(sibling))
            and (other["stem"], other["counter"]) == (match["stem"], match["counter"])}


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
