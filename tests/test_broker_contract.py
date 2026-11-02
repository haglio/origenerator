from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import config, osr2

CONTRACT = Path("broker") / "broker_contract.json"


def _promise() -> dict:
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_stamp_is_read_from_the_directory_the_broker_writes_it_to():
    named = _promise()["state_dir"]

    assert config.project_dir(named["checkout"]) / named["name"] == osr2.SHARED_STATE_DIR
