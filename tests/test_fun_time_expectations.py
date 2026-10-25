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
                           capture_output=True, text=True, encoding="utf-8",
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


def _is_read_by(written: str, reads: dict) -> bool:
    if "pattern" in reads:
        return re.fullmatch(reads["pattern"], written) is not None
    return sorted(json.loads(written)) == reads["keys"]


def test_fun_time_names_each_file_the_two_apps_hand_each_other_as_this_app_does(relied_on):
    assert {side: entry["file"] for side, entry in relied_on["handoff"].items()} == {
        side: entry["file"] for side, entry in contract.declaration()["handoff"].items()}


def test_what_either_app_writes_in_a_handoff_file_is_what_the_other_reads(relied_on):
    declared = contract.declaration()
    unread = [(side, written)
              for writer, reader in ((relied_on, declared), (declared, relied_on))
              for side, entry in writer["handoff"].items()
              for written in entry.get("writes", ())
              if not _is_read_by(written, reader["handoff"][side]["reads"])]

    assert unread == []


def test_every_takeover_fun_time_writes_is_taken_and_gone_once_read(relied_on, tmp_path):
    for written in relied_on["handoff"]["takeover"]["writes"]:
        takeover = tmp_path / contract.TAKEOVER_NAME
        takeover.write_text(written, encoding="utf-8")

        session = contract.take_the_takeover(
            tmp_path, pid=json.loads(written)[contract.TAKEOVER_PID])

        assert (session is not None, takeover.exists()) == (True, False), written
