from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from origenerator import config, evolver_export
from origenerator.config import project_dir

CONTRACT = "evolver_contract.json"


@dataclass(frozen=True)
class OurSide:
    library_root: Path
    inbox_dir: Path
    upscaled_dir: Path
    partial_marker: str


def our_side() -> OurSide:
    return OurSide(
        library_root=config.LIBRARY_ROOT,
        inbox_dir=config.EVOLVER_INBOX_DIR,
        upscaled_dir=config.EVOLVER_UPSCALED_DIR,
        partial_marker=evolver_export.PARTIAL_MARKER,
    )


def evolver_checkout() -> Path:
    return project_dir("evolver")


def _published(checkout: Path) -> dict | None:
    document = checkout / CONTRACT
    if not document.is_file():
        return None
    return json.loads(document.read_text(encoding="utf-8"))


def records_folder(checkout: Path, library_root: Path) -> Path | None:
    try:
        published = _published(checkout) or {}
    except (OSError, ValueError):
        return None
    folder = (published.get("library_record") or {}).get("folder")
    return library_root / Path(folder) if folder else None


def _differing(what: str, ours, theirs) -> str | None:
    if theirs is None or str(ours) == str(theirs):
        return None
    return f"{what}: this app has {ours}, Evolver has {theirs}"


def disagreements(ours: OurSide, checkout: Path) -> tuple[str, ...]:
    try:
        published = _published(checkout)
    except (OSError, ValueError) as unreadable:
        return (f"{checkout / CONTRACT} could not be read: {unreadable}",)
    if published is None:
        return ()

    relative = published.get("library_relative", {})

    def under_library(key):
        named = relative.get(key)
        return None if named is None else ours.library_root / Path(named)

    said = (
        _differing("the inbox a send lands in", ours.inbox_dir, under_library("inbox_dir")),
        _differing("the folder an upscale comes back from",
                   ours.upscaled_dir, under_library("upscaled_dir")),
        _differing("the mark a half-written copy wears",
                   ours.partial_marker, published.get("partial_marker")),
    )
    return tuple(line for line in said if line is not None)
