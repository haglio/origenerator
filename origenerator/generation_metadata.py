from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from origenerator import config, gallery
from origenerator.generation_config import merge_denormalized
from origenerator.output_places import OutputPlaces
from origenerator.provenance import BASIS, FILE_DATE, WORKFLOW_VERSION
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.frame_rate import NATIVE_FPS, frames_filled_in


@dataclass
class MetadataItem:
    label: str
    value: str
    copy: str | None = None
    reveal: str | None = None
    tooltip: str = ""


METADATA_TITLE = "Metadata"


@dataclass
class MetadataFacts:
    title: str
    items: list[MetadataItem]


def _output_path(file: dict) -> str:
    subfolder = file.get("subfolder") or ""
    filename = file.get("filename") or ""
    return f"{subfolder}/{filename}" if subfolder else filename


def _held_prefix(held_days: int | None) -> str:
    if held_days is None:
        return ""
    if held_days <= 0:
        return "(deleted today) "
    return f"({held_days} day{'s' if held_days != 1 else ''} in trash) "


def _places(given: OutputPlaces | None) -> OutputPlaces:
    return config.OUTPUT_PLACES if given is None else given


@dataclass(frozen=True)
class Dating:
    created_fallback: str = ""
    held_days: int | None = None


UNDATED = Dating()


def file_item(file: dict, label: str = "File", *,
              held_days: int | None = None, places: OutputPlaces | None = None) -> MetadataItem:
    filename = file.get("filename") or ""
    full = gallery.output_file_path(file, _places(places))
    return MetadataItem(label, _held_prefix(held_days) + _output_path(file),
                    copy=filename, reveal=str(full))


def created_item(file: dict, fallback: str = "", *,
                 places: OutputPlaces | None = None) -> MetadataItem:
    full = gallery.output_file_path(file, _places(places))
    try:
        stamp = datetime.fromtimestamp(full.stat().st_mtime).astimezone()
    except OSError:
        return MetadataItem("Created", str(fallback))
    return MetadataItem("Created", stamp.strftime("%Y-%m-%d %H:%M:%S"))


def metadata_facts(row: dict, upscale: Path | None = None, *,
                  name: str = "") -> MetadataFacts | None:
    listed = {version.file.get("filename")
              for version in gallery.displayed_versions(row, upscale)}
    files = [f for f in gallery.row_output_files(row)
             if f.get("filename") and f.get("filename") not in listed]
    items = [MetadataItem("Name", name, copy=name)] if name else []
    if files:
        held = row.get("days_in_trash")
        items += [file_item(f, held_days=held) for f in files]
        items.append(MetadataItem("Created", str(row.get("created_at", ""))))
    items += _frame_items(row)
    if row.get("provenance") and row.get("workflow_name") in WORKFLOW_REGISTRY:
        items.append(_version_line(json.loads(row["provenance"])))
    return MetadataFacts(METADATA_TITLE, items) if items else None


_LENGTH_KEYS = {"frame_count", "scene_frames"}
_FPS = f"{NATIVE_FPS:g} frames a second"
_FRAMES_TIP = (
    f"Frames from model: the frames WAN 2.2 made itself. It was trained on videos at {_FPS}, "
    f"so each frame it makes moves the scene 1/{NATIVE_FPS:g} of a second forward: asking it "
    "for more frames would only make the motion last longer, never smoother.\n\n"
    f"Total frames: the frames in the file. Above {_FPS}, the frames between the model's own "
    "are filled in afterward (interpolated), as many as the Frame Rate setting asks for.")


def _knows_its_frames(workflow, recorded: dict) -> bool:
    return (workflow is not None and "frame_rate" in workflow.default_params()
            and bool(_LENGTH_KEYS & recorded.keys()))


def _frame_items(row: dict) -> list[MetadataItem]:
    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name"))
    recorded = merge_denormalized(row)
    if not _knows_its_frames(workflow, recorded):
        return []
    params = {**workflow.default_params(), **recorded}
    made = workflow.video_frames(workflow.scene_plan(params))
    return [MetadataItem("Frames from model", str(made), tooltip=_FRAMES_TIP),
            MetadataItem("Total frames", str(frames_filled_in(made, params["frame_rate"])),
                         tooltip=_FRAMES_TIP)]


def _version_line(block: dict) -> MetadataItem:
    return MetadataItem("Workflow version", _version_text(block))


def _version_text(block: dict) -> str:
    version = block.get(WORKFLOW_VERSION)
    if not version:
        return "unknown"
    if block.get(BASIS) == FILE_DATE:
        return f"{version} (going by the file's date)"
    commit = block.get("app_commit")
    if not commit:
        return version
    edits = ", plus uncommitted edits" if block.get("app_dirty") else ""
    return f"{version} (app build {commit[:7]}{edits})"

