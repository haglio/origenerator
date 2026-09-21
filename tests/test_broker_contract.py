"""Where this app looks for the device's stamp, held to what the broker says.

The stamp is the only evidence the OSR2 is switched on, and it sits in one
directory three apps meet at: the broker writes it, a Fun Time session reads
it, and so does this app.  Those two are each configured with the path.  This
app has no such key, so it walks to that checkout and appends ``state`` in its
own source -- one app's directory layout written down inside another, where a
change to it would be found by nobody and the only symptom is an OSR2 reading
as switched off while it is plainly running.

The broker publishes ``broker_contract.json`` at its checkout root, which says
which checkout that directory is under.  Neither repo's gate clones the other,
so walking up to that document is the one place the two sides can be compared,
and the check says so where there is no broker beside this one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import config, osr2

CONTRACT = Path("broker") / "broker_contract.json"


def _promise() -> dict:
    """The broker's published document, found beside this checkout.

    Walked up from here rather than resolved through the content overlay: the
    overlay is git-ignored, so a worktree -- which is where every suite runs --
    has only the placeholder one, pointing at a library that is not there.
    """
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_stamp_is_read_from_the_directory_the_broker_writes_it_to():
    """Both halves of the path: the checkout it sits under, and the folder
    inside that checkout."""
    named = _promise()["state_dir"]

    assert config.project_dir(named["checkout"]) / named["name"] == osr2.SHARED_STATE_DIR
