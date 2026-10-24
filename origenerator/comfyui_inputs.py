"""ComfyUI opens a picture, video or sound only from its own input, output or temp
folder, resolved past any link into them, so a run names each file kept anywhere
else by a copy in ComfyUI's temp folder, which ComfyUI empties as it starts."""
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import NamedTuple

from origenerator.file_refs import OUTPUT_TAG, TEMP_TAG, reference_path, split_annotation
from origenerator.output_places import OutputPlaces

HANDED_OVER = "origenerator"
FILE_INPUTS = {"LoadImage": "image", "LoadVideo": "file", "LoadAudio": "audio"}


class ComfyFolders(NamedTuple):
    input: Path
    places: OutputPlaces
    temp: Path


def within_reach(payload: dict, folders: ComfyFolders) -> dict:
    return {node_id: _with_its_file_in_reach(node, folders) for node_id, node in payload.items()}


def _with_its_file_in_reach(node: dict, folders: ComfyFolders) -> dict:
    key = FILE_INPUTS.get(node.get("class_type"))
    ref = node.get("inputs", {}).get(key) if key else None
    if not isinstance(ref, str):
        return node
    return {**node, "inputs": {**node["inputs"], key: reachable(ref, folders)}}


def reachable(ref: str, folders: ComfyFolders) -> str:
    file = reference_path(ref, places=folders.places, input_dir=folders.input, temp_dir=folders.temp)
    if file is None or _inside(file, _folder_named_by(ref, folders)):
        return ref
    copy = _copied_in(file, folders.temp / HANDED_OVER)
    return f"{copy.relative_to(folders.temp).as_posix()} {TEMP_TAG}"


def _folder_named_by(ref: str, folders: ComfyFolders) -> Path:
    tag = split_annotation(ref)[1]
    return {OUTPUT_TAG: folders.places.comfyui, TEMP_TAG: folders.temp}.get(tag, folders.input)


def _inside(file: Path, folder: Path) -> bool:
    return file.resolve().is_relative_to(folder.resolve())


def _copied_in(file: Path, handed_over: Path) -> Path:
    copy = handed_over / _content_of(file) / file.name
    if not copy.is_file():
        copy.parent.mkdir(parents=True, exist_ok=True)
        partial = copy.with_name(f"{copy.stem}.partial.{uuid.uuid4().hex}")
        try:
            shutil.copyfile(file, partial)
            os.replace(partial, copy)
        finally:
            partial.unlink(missing_ok=True)
    return copy


def _content_of(file: Path) -> str:
    with file.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()[:12]
