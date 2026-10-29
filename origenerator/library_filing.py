from __future__ import annotations

import os
from pathlib import Path

from origenerator.file_numbers import NUMBERED, next_number, numbered
from origenerator.media import MediaType, media_type_from_filename
from origenerator.output_places import OutputPlaces, files_under, folders_in
from origenerator.trash import Trash
from origenerator.workflows.base import soundless_copies_of
from origenerator.workflows.video_writer import VIDEO_WRITER

ADD_ON_SCRATCH = frozenset({"VRGDG_TEMP"})


def saving_into_its_run_folder(payload: dict, places: OutputPlaces, prompt_id: str) -> dict:
    run = _run_subfolder(places, prompt_id)
    return {node_id: _saving_under(node, run) for node_id, node in payload.items()}


def _saving_under(node: dict, run: str) -> dict:
    prefix = node.get("inputs", {}).get("filename_prefix")
    if not isinstance(prefix, str):
        return node
    return {**node, "inputs": {**node["inputs"], "filename_prefix": f"{run}/{prefix}"}}


def saved_in_its_run_folder(payload: dict, places: OutputPlaces, prompt_id: str) -> dict:
    run = _run_subfolder(places, prompt_id)
    return {"outputs": {node_id: {"images": saved} for node_id, node in payload.items()
                        if (saved := _saved_by(node, run, places))}}


def _saved_by(node: dict, run: str, places: OutputPlaces) -> list[dict]:
    prefix = node.get("inputs", {}).get("filename_prefix")
    if not isinstance(prefix, str) or not prefix.startswith(f"{run}/"):
        return []
    subfolder, stem = prefix.rsplit("/", 1)
    folder = places.comfyui / subfolder
    names = sorted(name for name in (os.listdir(folder) if folder.is_dir() else [])
                   if (match := NUMBERED.match(name)) and match["stem"] == stem)
    if node.get("class_type") == VIDEO_WRITER:
        names = _videos_comfyui_reports(names)
    return [{"filename": name, "subfolder": subfolder, "type": "output"} for name in names]


def _videos_comfyui_reports(names: list[str]) -> list[str]:
    videos = [{"filename": name} for name in names
              if media_type_from_filename(name) == MediaType.VIDEO]
    silent = {copy["filename"] for copy in soundless_copies_of(videos)}
    return [video["filename"] for video in videos if video["filename"] not in silent]


def file_into_library(files: list[dict], places: OutputPlaces, prompt_id: str) -> list[dict]:
    run = _run_subfolder(places, prompt_id)
    held = _held_in_trash(places)
    filed: dict[tuple[str, str], tuple[str, str]] = {}
    for record in files:
        subfolder, name = _key(record)
        if (subfolder, name) in filed or not subfolder.startswith(f"{run}/"):
            continue
        kind = subfolder.removeprefix(f"{run}/")
        moved = _file_into_its_home(places.comfyui / subfolder, name, places.folder(kind), held)
        filed.update({(subfolder, was): (kind, now) for was, now in moved.items()})
    _remove_what_is_left_empty(places.run(prompt_id))
    return [_as_filed(record, filed) for record in files]


def file_what_comfyui_left(places: OutputPlaces) -> int:
    if places.keeps_outputs_in_comfyuis_folder():
        return 0
    held = _held_in_trash(places)
    return sum(_file_everything_under(top, places, held) for top in folders_in(places.comfyui)
               if top != places.working and top.name not in ADD_ON_SCRATCH)


def _held_in_trash(places: OutputPlaces) -> set[str]:
    return Trash(places.trash).held_names() if places.trash is not None else set()


def _file_everything_under(top: Path, places: OutputPlaces, held: set[str]) -> int:
    filed = 0
    for folder, names in files_under(top):
        home = places.folder(folder.relative_to(places.comfyui).as_posix())
        for name in names:
            if (folder / name).is_file():
                filed += len(_file_into_its_home(folder, name, home, held))
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


def _file_into_its_home(waiting: Path, name: str, home: Path,
                        held: set[str]) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    filed_as = _names_in_its_home(waiting, name, home, held)
    for was, now in filed_as.items():
        os.rename(waiting / was, home / now)
    return filed_as


def _names_in_its_home(waiting: Path, name: str, home: Path,
                       held: set[str]) -> dict[str, str]:
    match = NUMBERED.match(name)
    if match is None:
        return {} if os.path.lexists(home / name) else {name: name}
    number = next_number(match["stem"], [home], held)
    return {sibling: numbered(sibling, match["stem"], number)
            for sibling in os.listdir(waiting)
            if (other := NUMBERED.match(sibling))
            and (other["stem"], other["counter"]) == (match["stem"], match["counter"])}


def _key(record: dict) -> tuple[str, str]:
    return (record.get("subfolder") or "").replace("\\", "/"), record.get("filename") or ""


def _as_filed(record: dict, filed: dict[tuple[str, str], tuple[str, str]]) -> dict:
    kind_and_name = filed.get(_key(record))
    if kind_and_name is None:
        return record
    kind, name = kind_and_name
    return {**record, "subfolder": kind, "filename": name}
