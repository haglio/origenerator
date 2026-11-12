from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import config, evolver_export

CONTRACT = Path("evolver") / "evolver_contract.json"


def _promise() -> dict:
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_folders_this_app_sends_to_are_the_ones_evolver_watches():
    relative = _promise()["library_relative"]
    sent_to = {"inbox_dir": config.EVOLVER_INBOX_DIR}

    watched = {name: config.LIBRARY_ROOT / Path(relative[name])
               for name in sent_to if name in relative}

    assert watched == sent_to


def test_a_copy_still_being_written_wears_the_name_evolver_walks_past():
    marker = _promise()["partial_marker"]

    partial = evolver_export.partial_name(Path("some-clip.mp4"))

    assert marker in partial.name
