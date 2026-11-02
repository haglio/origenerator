from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from origenerator import config, gallery
from origenerator.output_places import OutputPlaces
from origenerator.provenance import BASIS, FILE_DATE, WORKFLOW_VERSION
from origenerator.workflows import WORKFLOW_REGISTRY


@dataclass
class BasicItem:
    label: str
    value: str
    copy: str | None = None
    reveal: str | None = None


BASIC_TITLE = "Basic"


@dataclass
class BasicFacts:
    title: str
    items: list[BasicItem]


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
              held_days: int | None = None, places: OutputPlaces | None = None) -> BasicItem:
    filename = file.get("filename") or ""
    full = gallery.output_file_path(file, _places(places))
    return BasicItem(label, _held_prefix(held_days) + _output_path(file),
                    copy=filename, reveal=str(full))


def created_item(file: dict, fallback: str = "", *,
                 places: OutputPlaces | None = None) -> BasicItem:
    full = gallery.output_file_path(file, _places(places))
    try:
        stamp = datetime.fromtimestamp(full.stat().st_mtime).astimezone()
    except OSError:
        return BasicItem("Created", str(fallback))
    return BasicItem("Created", stamp.strftime("%Y-%m-%d %H:%M:%S"))


def basic_facts(row: dict, upscale: Path | None = None, *,
                  name: str = "") -> BasicFacts | None:
    listed = {version.file.get("filename")
              for version in gallery.displayed_versions(row, upscale)}
    files = [f for f in gallery.row_output_files(row)
             if f.get("filename") and f.get("filename") not in listed]
    items = [BasicItem("Name", name, copy=name)] if name else []
    if files:
        held = row.get("days_in_trash")
        items += [file_item(f, held_days=held) for f in files]
        items.append(BasicItem("Created", str(row.get("created_at", ""))))
    if row.get("provenance") and row.get("workflow_name") in WORKFLOW_REGISTRY:
        items.append(_version_line(json.loads(row["provenance"])))
    return BasicFacts(BASIC_TITLE, items) if items else None


def _version_line(block: dict) -> BasicItem:
    return BasicItem("Workflow version", _version_text(block))


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

