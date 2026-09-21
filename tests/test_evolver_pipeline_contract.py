"""What this repo hands Evolver, held to what Evolver promises.

A send copies the video into a folder of Evolver's and the gallery later reads
Evolver's upscale back out of another -- both spelled here, from reading that
repo's source, with nothing comparing them.  A folder renamed over there left
this app dropping clips where nothing ingests them, and every suite stayed
green.

Evolver publishes ``evolver_contract.json`` at its checkout root now.  These
hold this repo's paths and its half-written name to it.  Neither gate clones
the other, so on a machine with no Evolver beside this one there is nothing to
compare and the check says so.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import config, evolver_export

CONTRACT = Path("evolver") / "evolver_contract.json"


def _promise() -> dict:
    """Evolver's published document, found beside this checkout.

    Walked up from here rather than resolved through the content overlay: the
    overlay is git-ignored, so a worktree -- which is where every suite runs --
    has only the placeholder one, pointing at a library that is not there.  The
    walk lands on the checkout beside the primary from a worktree and from a
    clone alike.
    """
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_folders_this_app_sends_to_are_the_ones_evolver_watches():
    """Library-relative in the document, because the library root is private
    and each app resolves it from its own overlay."""
    relative = _promise()["library_relative"]

    under_library = {name: config.LIBRARY_ROOT / Path(value)
                     for name, value in relative.items()}

    assert under_library == {"inbox_dir": config.EVOLVER_INBOX_DIR,
                             "upscaled_dir": config.EVOLVER_UPSCALED_DIR}


def test_a_copy_still_being_written_wears_the_name_evolver_walks_past():
    """The marker is the whole of why a run of Evolver's pipeline never ingests
    half a video, and it has to be IN the name, not merely near it."""
    marker = _promise()["partial_marker"]

    partial = evolver_export.partial_name(Path("some-clip.mp4"))

    assert marker in partial.name
