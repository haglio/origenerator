"""What this app and Evolver have agreed about the hand-off, and whether they still agree.

A send copies a clip into a folder of Evolver's, and the gallery reads Evolver's
upscale back out of another.  Four values decide where it lands and whether it is
picked up: the two folders, the marker a half-written copy wears, and the
sub-folder Evolver routes this app's Genau clips by.  Every one of them is
written down twice, once in each app, and a rename on either side left clips
arriving nowhere with both apps silent and every suite green.

Two of the four are published -- Evolver writes ``evolver_contract.json`` at its
checkout root -- and ``tests/test_evolver_pipeline_contract.py`` holds this
repo's copies against them.  That check skips where no Evolver sits beside the
checkout, which is every run of this repo's gate, so on the one machine that has
both apps installed nothing compared anything.  This is that check's runtime
twin: the app asks at startup and says what disagrees.

The other two cannot be published at all.  A folder inside the library is
library vocabulary, which the sanitize guard keeps out of a public commit, so
``genau_source`` lives in a git-ignored overlay on each side and a comparison is
the only thing that can hold the two together.

Nothing to compare against is not a disagreement: a fresh clone, and every gate
run, has no Evolver beside it and is answered with nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app_support import overlay

from origenerator import config, evolver_export
from origenerator.config import project_dir

CONTRACT = "evolver_contract.json"


@dataclass(frozen=True)
class OurSide:
    """This app's half of the agreement, as it will actually behave."""

    library_root: Path
    inbox_dir: Path
    upscaled_dir: Path
    partial_marker: str
    genau_source: str


def our_side() -> OurSide:
    """What this app is running with, read off the modules that decide it."""
    return OurSide(
        library_root=config.LIBRARY_ROOT,
        inbox_dir=config.EVOLVER_INBOX_DIR,
        upscaled_dir=config.EVOLVER_UPSCALED_DIR,
        partial_marker=evolver_export.PARTIAL_MARKER,
        genau_source=config.GENAU_SOURCE,
    )


def evolver_checkout() -> Path:
    """Where Evolver is, or would be; :func:`disagreements` handles its absence."""
    return project_dir("evolver")


def _published(checkout: Path) -> dict | None:
    document = checkout / CONTRACT
    if not document.is_file():
        return None
    return json.loads(document.read_text(encoding="utf-8"))


def _their_genau_source(checkout: Path) -> str | None:
    """The lane folder from Evolver's own overlay, local first as it loads it."""
    local, example = checkout / "content.local.json", checkout / "content.example.json"
    if not local.exists() and not example.exists():
        return None
    return overlay.read_overlay(local, example).get("genau_source")


def _differing(what: str, ours, theirs) -> str | None:
    if theirs is None or str(ours) == str(theirs):
        return None
    return f"{what}: this app has {ours}, Evolver has {theirs}"


def disagreements(ours: OurSide, checkout: Path) -> tuple[str, ...]:
    """Every value the two apps no longer spell the same, in words.

    A read that fails is itself reported rather than raised: this runs before
    there is a window, and a broken file in another repo must not be how this
    app declines to open.
    """
    try:
        published = _published(checkout)
        theirs_genau = _their_genau_source(checkout)
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
        _differing("the folder Genau clips are routed by", ours.genau_source, theirs_genau),
    )
    return tuple(line for line in said if line is not None)
