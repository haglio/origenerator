"""The read-only facts about one generation that belong with neither the params
nor the form: its name, the output file, when the run happened, and which
workflow version made it.

The gallery's Generate pane tab is an editable :class:`GenerateTab`. It renders
the prompts and every parameter the workflow lays out as fields; whatever else a
row carries — an import's extras, hidden passthrough like VAE or CLIP — rides
along unshown, as ParamForm keeps it. So what is left for this block is its name,
the output file, its timestamp and the workflow version, shown as a compact
``Basic`` section above the form.

An image's files are not one of those things any more: each is a version of the
image, made by its own enhancement at its own settings and at its own moment, so
each is listed down in the version list beside the version that produced it —
where the settings that made it already are — rather than pooled in one block at
the top under a label naming a version you then have to go and find. What stays
here is what no version claims: a video's file, and the siblings of a batch (which
are separate results of one run, not versions of each other).

Kept Qt-free so the section/item model is unit-testable directly;
``gui/basic_section.py`` does the rendering.
"""
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
    """One line in a section, rendered as ``label: value``.

    ``copy`` drives a copy-to-clipboard button: ``None`` shows no button, a
    non-empty string is what the button copies. ``reveal`` drives a
    Show-in-Explorer button: ``None`` shows no button, otherwise the absolute
    path on disk the button reveals (selected in the OS file manager).
    """

    label: str
    value: str
    copy: str | None = None
    reveal: str | None = None


BASIC_TITLE = "Basic"   # the block draws it for a row whose facts come to nothing


@dataclass
class BasicFacts:
    title: str
    items: list[BasicItem]


def _output_path(file: dict) -> str:
    subfolder = file.get("subfolder") or ""
    filename = file.get("filename") or ""
    return f"{subfolder}/{filename}" if subfolder else filename


def _held_prefix(held_days: int | None) -> str:
    """How long this file's generation has been in the trash, for the front of
    its File line — nothing at all for an item that hasn't been deleted.

    It leads the line because the line is where you go to find out what a file
    *is*, and for a deleted one "how long until it's gone" is part of that. The
    Trash collection's tiles carry the other half of the arithmetic (how many days it
    has left); this says how long it has been sitting there.
    """
    if held_days is None:
        return ""
    if held_days <= 0:
        return "(deleted today) "
    return f"({held_days} day{'s' if held_days != 1 else ''} in trash) "


def _places(given: OutputPlaces | None) -> OutputPlaces:
    return config.OUTPUT_PLACES if given is None else given


def file_item(file: dict, label: str = "File", *,
              held_days: int | None = None, places: OutputPlaces | None = None) -> BasicItem:
    """One output file as a row: its path, a copy of just its filename (dropping
    the image/ or video/ subfolder the displayed path carries), and a reveal of
    its absolute location — in the library, or wherever the Trash has
    since moved it.

    ``held_days`` is set only for a deleted item, and puts how long it has been
    in the trash in front of the path.

    Shared with the version list, which puts this exact row beside the version it
    belongs to — the same file information, wherever the file is listed."""
    filename = file.get("filename") or ""
    full = gallery.output_file_path(file, _places(places))
    return BasicItem(label, _held_prefix(held_days) + _output_path(file),
                    copy=filename, reveal=str(full))


def created_item(file: dict, fallback: str = "", *,
                 places: OutputPlaces | None = None) -> BasicItem:
    """When one output file was written, from the file itself.

    Per file rather than per row, because an image's versions were made at
    different moments — the enhancement you queued this evening sits beside a
    render from last week, and one ``created_at`` on the row can only be honest
    about one of them. Falls back to the row's own timestamp when the file is
    gone from disk."""
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

