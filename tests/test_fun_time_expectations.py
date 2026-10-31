"""What Fun Time relies on of this app, held to this app before it ships.

Fun Time publishes it as its tests/origenerator_expectations.json, read off the
code that relies on it, and holds what this app has shipped to it.  Read here
from Fun Time's main, a change on this side that would leave a room relying on
something this app no longer offers is refused before it ships, rather than
turning Fun Time red after it has.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from app_support.siblings import sibling_checkout
from app_support.subprocess_utils import hidden_subprocess_kwargs

from origenerator import fun_time_mode as contract
from tests.test_hosted_launch_contract import flags_the_parser_accepts

EXPECTATIONS = "tests/origenerator_expectations.json"


@pytest.fixture(scope="module")
def relied_on() -> dict:
    try:
        fun_time = sibling_checkout("fun_time", near=Path(__file__))
    except RuntimeError:
        pytest.skip("no fun_time checkout beside this one")
    shown = subprocess.run(["git", "show", f"origin/HEAD:{EXPECTATIONS}"], cwd=str(fun_time),
                           capture_output=True, text=True, encoding="utf-8", check=False,
                           **hidden_subprocess_kwargs())
    if shown.returncode:
        pytest.fail(f"{fun_time}: {shown.stderr}")
    return json.loads(shown.stdout)


def test_fun_time_runs_this_module_and_finds_the_caption_its_window_wears(relied_on):
    assert (relied_on["module"], relied_on["window_title"]) == (
        contract.MODULE, contract.WINDOW_TITLE)


def test_every_flag_of_every_launch_fun_time_makes_is_one_this_app_takes(relied_on):
    refused = {launch: sorted(set(flags) - flags_the_parser_accepts())
               for launch, flags in relied_on["launches"].items()}

    assert not any(refused.values()), refused


def test_every_flag_this_app_requires_is_carried_by_every_launch_fun_time_makes(relied_on):
    missing = {launch: sorted(set(contract.required_flags()) - set(flags))
               for launch, flags in relied_on["launches"].items()}

    assert not any(missing.values()), missing


def test_this_app_reads_every_word_a_headset_writes(relied_on):
    assert set(relied_on["headset_words"]) <= set(contract.HEADSET_WORDS)


def test_this_app_declares_every_line_a_room_writes(relied_on):
    patterns = contract.command_patterns()

    assert [line for line in relied_on["command_lines"]
            if not any(re.fullmatch(pattern, line) for pattern in patterns)] == []


def test_this_app_takes_when_a_line_was_said_in_the_field_fun_time_fills(relied_on):
    field = relied_on.get("said_at_field")

    assert not field or "{" + field + "}" in contract.declaration()["said_at_suffix"]
