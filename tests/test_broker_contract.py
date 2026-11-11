from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import config, osr2

CONTRACT = Path("broker") / "broker_contract.json"


def _broker_contract_found_by_walking_up_from_here() -> dict:
    # git leaves an ignored file out of a worktree, so the content overlay there is only the placeholder.
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_stamp_is_read_from_the_directory_the_broker_writes_it_to():
    named = _broker_contract_found_by_walking_up_from_here()["state_dir"]

    assert config.project_dir(named["checkout"]) / named["name"] == osr2.SHARED_STATE_DIR, (
        "this app writes the Broker's directory layout into its own source, where a change to "
        "it would be found by nobody, and neither repo's gate clones the other, so this is the "
        "one place the two can be compared")
